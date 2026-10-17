package ruiner;

import skadistats.clarity.model.CombatLogEntry;
import skadistats.clarity.model.Entity;
import skadistats.clarity.model.FieldPath;
import skadistats.clarity.processor.entities.Entities;
import skadistats.clarity.processor.entities.OnEntityCreated;
import skadistats.clarity.processor.entities.OnEntityDeleted;
import skadistats.clarity.processor.entities.OnEntityPropertyChanged;
import skadistats.clarity.processor.gameevents.OnCombatLogEntry;
import skadistats.clarity.processor.entities.UsesEntities;
import skadistats.clarity.processor.reader.OnMessage;
import skadistats.clarity.processor.reader.OnTickEnd;
import skadistats.clarity.processor.runner.Context;
import skadistats.clarity.processor.runner.SimpleRunner;
import skadistats.clarity.source.MappedFileSource;
import skadistats.clarity.wire.dota.common.proto.DOTACombatLog.CMsgDOTACombatLogEntry;
import skadistats.clarity.wire.dota.common.proto.DOTACombatLog.DOTA_COMBATLOG_TYPES;
import skadistats.clarity.wire.dota.common.proto.DOTAUserMessages.CDOTAUserMsg_SpectatorPlayerUnitOrders;

import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Достаёт из реплея то, чего нет в OpenDota:
 * время каждого приказа игрока (для AFK), открытия панели статистики (таблицы),
 * позицию, жизнь, золото и нетворс героя раз в секунду, полосы порядочности и вежливости,
 * применения предметов, строения и варды с координатами.
 *
 * Время событий — в тиках демо; перевод в игровое время — по меткам времени боевого лога (anchors).
 */
@UsesEntities
public class Parse {

    static final int PLAYERS = 10;
    static final int SAMPLE_EVERY_TICKS = 30;

    // Игрок в событиях клиента = m_nPlayerID / 2 (0..9).
    final List<List<Integer>> orderTicks = new ArrayList<>();
    final List<List<int[]>> statsPanel = new ArrayList<>();   // [tick, value]
    final List<List<int[]>> queryUnit = new ArrayList<>();    // [tick, 0 — снял выделение, 1 — юнит, 2 — герой]
    final List<List<float[]>> samples = new ArrayList<>();    // [tick, x, y, alive, gold, networth]
    final List<String[]> itemUses = new ArrayList<>();        // [timestamp, hero npc, item]
    final Map<Integer, MapObject> buildings = new LinkedHashMap<>();
    final Map<Integer, MapObject> wards = new LinkedHashMap<>();
    final Map<Integer, Integer> heroHandleToPlayer = new HashMap<>();
    final String[] names = new String[PLAYERS];
    final long[] steamIds = new long[PLAYERS];
    final String[] heroClass = new String[PLAYERS];
    final List<float[]> anchors = new ArrayList<>();          // [tick, combat log timestamp]
    float gameStartTime, gameEndTime;
    int[] behaviorLevel = new int[PLAYERS];
    int[] commLevel = new int[PLAYERS];
    int[] commandsIssued = new int[PLAYERS];
    float millisPerTick = 1000f / 30f;
    int lastAnchorTick = -1000;

    Parse() {
        for (int i = 0; i < PLAYERS; i++) {
            orderTicks.add(new ArrayList<>());
            statsPanel.add(new ArrayList<>());
            queryUnit.add(new ArrayList<>());
            samples.add(new ArrayList<>());
            behaviorLevel[i] = -1;
            commLevel[i] = -1;
            commandsIssued[i] = -1;
        }
    }

    static int playerOf(Entity controller) {
        if (controller == null || !controller.hasProperty("m_nPlayerID")) return -1;
        int id = controller.getProperty("m_nPlayerID");
        int p = id / 2;
        return id >= 0 && id % 2 == 0 && p < PLAYERS ? p : -1;
    }

    @OnMessage(CDOTAUserMsg_SpectatorPlayerUnitOrders.class)
    public void onOrder(Context ctx, CDOTAUserMsg_SpectatorPlayerUnitOrders o) {
        Entity e = ctx.getProcessor(Entities.class).getByIndex(o.getEntindex());
        int p = e != null && "CDOTAPlayerController".equals(e.getDtClass().getDtName()) ? playerOf(e) : -1;
        if (p >= 0) orderTicks.get(p).add(ctx.getTick());
    }

    @OnMessage(CMsgDOTACombatLogEntry.class)
    public void onCombatLog(Context ctx, CMsgDOTACombatLogEntry e) {
        if (ctx.getTick() - lastAnchorTick >= SAMPLE_EVERY_TICKS && e.getTimestamp() > 0) {
            anchors.add(new float[]{ctx.getTick(), e.getTimestamp()});
            lastAnchorTick = ctx.getTick();
        }
    }

    static final int INVALID_HANDLE = 16777215;

    /** Строение или вард на карте: появился и исчез в такие-то тики. */
    static final class MapObject {
        String kind;
        int team, owner = -1, created, deleted = -1;
        float x, y;
    }

    @OnCombatLogEntry
    public void onCombatLogEntry(CombatLogEntry e) {
        if (e.getType() != DOTA_COMBATLOG_TYPES.DOTA_COMBATLOG_ITEM || !e.isAttackerHero() || e.isAttackerIllusion()) return;
        String hero = e.getAttackerName(), item = e.getInflictorName();
        if (hero == null || item == null) return;
        itemUses.add(new String[]{String.valueOf(e.getTimestamp()), hero, item});
    }

    static final String BUILDING_CLASSES = "CDOTA_BaseNPC_(Tower|Barracks|Fort|Watch_Tower)";
    static final String WARD_CLASSES = "CDOTA_NPC_Observer_Ward(_TrueSight)?";

    @OnEntityCreated(classPattern = BUILDING_CLASSES)
    public void onBuildingCreated(Context ctx, Entity e) {
        MapObject o = mapObject(ctx, e, e.getDtClass().getDtName().replace("CDOTA_BaseNPC_", "").toLowerCase());
        buildings.put(e.getHandle(), o);
    }

    @OnEntityDeleted(classPattern = BUILDING_CLASSES)
    public void onBuildingDeleted(Context ctx, Entity e) {
        MapObject o = buildings.get(e.getHandle());
        if (o != null) o.deleted = ctx.getTick();
    }

    @OnEntityCreated(classPattern = WARD_CLASSES)
    public void onWardCreated(Context ctx, Entity e) {
        MapObject o = mapObject(ctx, e, e.getDtClass().getDtName().endsWith("TrueSight") ? "sentry" : "observer");
        if (e.hasProperty("m_hOwnerEntity")) {
            int h = e.getProperty("m_hOwnerEntity");
            Entity owner = h == INVALID_HANDLE ? null : ctx.getProcessor(Entities.class).getByHandle(h);
            if (owner != null && "CDOTAPlayerController".equals(owner.getDtClass().getDtName())) o.owner = playerOf(owner);
            else o.owner = heroHandleToPlayer.getOrDefault(h, -1);
        }
        wards.put(e.getHandle(), o);
    }

    @OnEntityDeleted(classPattern = WARD_CLASSES)
    public void onWardDeleted(Context ctx, Entity e) {
        MapObject o = wards.get(e.getHandle());
        if (o != null) o.deleted = ctx.getTick();
    }

    static MapObject mapObject(Context ctx, Entity e, String kind) {
        MapObject o = new MapObject();
        o.kind = kind;
        o.team = e.hasProperty("m_iTeamNum") ? ((Number) e.getProperty("m_iTeamNum")).intValue() : 0;
        o.x = cellCoord(e, "X");
        o.y = cellCoord(e, "Y");
        o.created = ctx.getTick();
        return o;
    }

    @OnEntityPropertyChanged(classPattern = "CDOTAPlayerController", propertyPattern = "m_iStatsPanel")
    public void onStatsPanel(Context ctx, Entity e, FieldPath fp) {
        int p = playerOf(e);
        if (p < 0) return;
        int value = e.getPropertyForFieldPath(fp);
        statsPanel.get(p).add(new int[]{ctx.getTick(), value});
    }

    @OnEntityPropertyChanged(classPattern = "CDOTAPlayerController", propertyPattern = "m_hSpectatorQueryUnit")
    public void onQueryUnit(Context ctx, Entity e, FieldPath fp) {
        int p = playerOf(e);
        if (p < 0) return;
        int handle = e.getPropertyForFieldPath(fp);
        Entity u = handle == INVALID_HANDLE ? null : ctx.getProcessor(Entities.class).getByHandle(handle);
        int kind = u == null ? 0 : u.getDtClass().getDtName().startsWith("CDOTA_Unit_Hero_") ? 2 : 1;
        queryUnit.get(p).add(new int[]{ctx.getTick(), kind});
    }

    @OnTickEnd
    public void onTickEnd(Context ctx, boolean synthetic) {
        millisPerTick = ctx.getMillisPerTick();
        if (ctx.getTick() % SAMPLE_EVERY_TICKS != 0) return;
        Entities entities = ctx.getProcessor(Entities.class);
        Entity radiant = byClass(entities, "CDOTA_DataRadiant"), dire = byClass(entities, "CDOTA_DataDire");
        entities.stream()
                .filter(e -> "CDOTAPlayerController".equals(e.getDtClass().getDtName()))
                .forEach(c -> {
                    int p = playerOf(c);
                    if (p < 0) return;
                    if (names[p] == null && c.hasProperty("m_iszPlayerName")) {
                        names[p] = c.getProperty("m_iszPlayerName");
                        Object sid = c.hasProperty("m_steamID") ? c.getProperty("m_steamID") : null;
                        if (sid instanceof Number n) steamIds[p] = n.longValue();
                    }
                    if (!c.hasProperty("m_hAssignedHero")) return;
                    int handle = c.getProperty("m_hAssignedHero");
                    Entity hero = entities.getByHandle(handle);
                    if (hero == null) return;
                    heroClass[p] = hero.getDtClass().getDtName();
                    heroHandleToPlayer.put(handle, p);
                    float x = cellCoord(hero, "X"), y = cellCoord(hero, "Y");
                    int life = hero.hasProperty("m_lifeState") ? hero.<Integer>getProperty("m_lifeState") : 0;
                    Entity team = p < 5 ? radiant : dire;
                    String d = "m_vecDataTeam." + String.format("%04d", p % 5) + ".";
                    int gold = intProp(team, d + "m_iReliableGold") + intProp(team, d + "m_iUnreliableGold");
                    int nw = intProp(team, d + "m_iNetWorth");
                    samples.get(p).add(new float[]{ctx.getTick(), x, y, life == 0 ? 1 : 0, gold, nw});
                });
        readGameRules(entities);
        readPlayerResource(entities);
    }

    static Entity byClass(Entities entities, String dtName) {
        return entities.stream().filter(e -> dtName.equals(e.getDtClass().getDtName())).findFirst().orElse(null);
    }

    static int intProp(Entity e, String name) {
        return e != null && e.hasProperty(name) ? ((Number) e.getProperty(name)).intValue() : 0;
    }

    static float cellCoord(Entity hero, String axis) {
        String cell = "CBodyComponent.m_cell" + axis, vec = "CBodyComponent.m_vec" + axis;
        if (!hero.hasProperty(cell) || !hero.hasProperty(vec)) return Float.NaN;
        int c = hero.getProperty(cell);
        float v = hero.getProperty(vec);
        return c * 128f + v - 16384f;
    }

    void readGameRules(Entities entities) {
        Entity gr = entities.stream().filter(e -> "CDOTAGamerulesProxy".equals(e.getDtClass().getDtName()))
                .findFirst().orElse(null);
        if (gr == null) return;
        if (gr.hasProperty("m_pGameRules.m_flGameStartTime")) gameStartTime = gr.getProperty("m_pGameRules.m_flGameStartTime");
        if (gr.hasProperty("m_pGameRules.m_flGameEndTime")) gameEndTime = gr.getProperty("m_pGameRules.m_flGameEndTime");
    }

    void readPlayerResource(Entities entities) {
        Entity pr = entities.stream().filter(e -> "CDOTA_PlayerResource".equals(e.getDtClass().getDtName()))
                .findFirst().orElse(null);
        Entity radiant = entities.stream().filter(e -> "CDOTA_DataRadiant".equals(e.getDtClass().getDtName()))
                .findFirst().orElse(null);
        Entity dire = entities.stream().filter(e -> "CDOTA_DataDire".equals(e.getDtClass().getDtName()))
                .findFirst().orElse(null);
        for (int i = 0; i < PLAYERS; i++) {
            String idx = String.format("%04d", i);
            if (pr != null) {
                String b = "m_vecPlayerData." + idx + ".m_nBehaviorLevel", c = "m_vecPlayerData." + idx + ".m_nCommLevel";
                if (pr.hasProperty(b)) behaviorLevel[i] = ((Number) pr.getProperty(b)).intValue();
                if (pr.hasProperty(c)) commLevel[i] = ((Number) pr.getProperty(c)).intValue();
            }
            Entity team = i < 5 ? radiant : dire;
            String cmd = "m_vecDataTeam." + String.format("%04d", i % 5) + ".m_iCommandsIssued";
            if (team != null && team.hasProperty(cmd)) commandsIssued[i] = ((Number) team.getProperty(cmd)).intValue();
        }
    }

    /** Игровое время (сек от горна) для тика демо — по ближайшей предыдущей метке боевого лога. */
    double gameTime(int tick) {
        if (anchors.isEmpty()) return Double.NaN;
        int lo = 0, hi = anchors.size() - 1, best = 0;
        while (lo <= hi) {
            int mid = (lo + hi) >>> 1;
            if (anchors.get(mid)[0] <= tick) { best = mid; lo = mid + 1; } else hi = mid - 1;
        }
        float[] a = anchors.get(best);
        return a[1] + (tick - a[0]) * millisPerTick / 1000.0 - gameStartTime;
    }

    public static void run(String path, String outPath) throws Exception {
        Parse p = new Parse();
        try (var source = new MappedFileSource(path)) {
            new SimpleRunner(source).runWith(p);
        }
        try (PrintStream out = outPath == null ? System.out : new PrintStream(outPath, StandardCharsets.UTF_8)) {
            p.write(out);
        }
    }

    void write(PrintStream out) {
        StringBuilder sb = new StringBuilder(1 << 20);
        sb.append("{\"version\":2,\"game_start_time\":").append(f(gameStartTime))
          .append(",\"duration\":").append(f(gameEndTime - gameStartTime)).append(",\"players\":[");
        for (int i = 0; i < PLAYERS; i++) {
            if (i > 0) sb.append(',');
            sb.append("{\"index\":").append(i)
              .append(",\"name\":").append(str(names[i]))
              .append(",\"steam_id\":").append(steamIds[i])
              .append(",\"hero_class\":").append(str(heroClass[i]))
              .append(",\"behavior_level\":").append(behaviorLevel[i])
              .append(",\"comm_level\":").append(commLevel[i])
              .append(",\"commands_issued\":").append(commandsIssued[i])
              .append(",\"orders\":[");
            List<Integer> ot = orderTicks.get(i);
            for (int j = 0; j < ot.size(); j++) {
                if (j > 0) sb.append(',');
                sb.append(f(gameTime(ot.get(j))));
            }
            sb.append("],\"stats_panel\":[");
            List<int[]> sp = statsPanel.get(i);
            for (int j = 0; j < sp.size(); j++) {
                if (j > 0) sb.append(',');
                sb.append('[').append(f(gameTime(sp.get(j)[0]))).append(',').append(sp.get(j)[1]).append(']');
            }
            sb.append("],\"query_unit\":[");
            List<int[]> qu = queryUnit.get(i);
            for (int j = 0; j < qu.size(); j++) {
                if (j > 0) sb.append(',');
                sb.append('[').append(f(gameTime(qu.get(j)[0]))).append(',').append(qu.get(j)[1]).append(']');
            }
            sb.append("],\"samples\":[");
            List<float[]> sm = samples.get(i);
            for (int j = 0; j < sm.size(); j++) {
                if (j > 0) sb.append(',');
                float[] s = sm.get(j);
                sb.append('[').append(f(gameTime((int) s[0]))).append(',').append(Math.round(s[1])).append(',')
                  .append(Math.round(s[2])).append(',').append((int) s[3]).append(',').append((int) s[4])
                  .append(',').append((int) s[5]).append(']');
            }
            sb.append("]}");
        }
        sb.append("],\"item_uses\":[");
        for (int j = 0; j < itemUses.size(); j++) {
            String[] u = itemUses.get(j);
            if (j > 0) sb.append(',');
            sb.append('[').append(f(Float.parseFloat(u[0]) - gameStartTime)).append(',').append(str(u[1]))
              .append(',').append(str(u[2])).append(']');
        }
        sb.append("],\"buildings\":");
        writeObjects(sb, buildings);
        sb.append(",\"wards\":");
        writeObjects(sb, wards);
        sb.append('}');
        out.print(sb);
    }

    void writeObjects(StringBuilder sb, Map<Integer, MapObject> objects) {
        sb.append('[');
        boolean first = true;
        for (MapObject o : objects.values()) {
            if (!first) sb.append(',');
            first = false;
            sb.append("{\"kind\":").append(str(o.kind)).append(",\"team\":").append(o.team)
              .append(",\"owner\":").append(o.owner)
              .append(",\"x\":").append(Math.round(o.x)).append(",\"y\":").append(Math.round(o.y))
              .append(",\"created\":").append(f(gameTime(o.created)))
              .append(",\"deleted\":").append(o.deleted < 0 ? "null" : f(gameTime(o.deleted))).append('}');
        }
        sb.append(']');
    }

    static String f(double v) {
        if (Double.isNaN(v) || Double.isInfinite(v)) return "null";
        return String.format(Locale.ROOT, "%.1f", v);
    }

    static String str(String s) {
        if (s == null) return "null";
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"' -> b.append("\\\"");
                case '\\' -> b.append("\\\\");
                default -> {
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c)); else b.append(c);
                }
            }
        }
        return b.append('"').toString();
    }
}
