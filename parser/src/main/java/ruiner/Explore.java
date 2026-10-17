package ruiner;

import skadistats.clarity.protobuf.GeneratedMessage;
import skadistats.clarity.model.Entity;
import skadistats.clarity.model.FieldPath;
import skadistats.clarity.model.GameEvent;
import skadistats.clarity.processor.entities.Entities;
import skadistats.clarity.processor.entities.UsesEntities;
import skadistats.clarity.processor.gameevents.OnGameEvent;
import skadistats.clarity.processor.reader.OnMessage;
import skadistats.clarity.processor.reader.OnTickEnd;
import skadistats.clarity.processor.runner.Context;
import skadistats.clarity.processor.runner.SimpleRunner;
import skadistats.clarity.source.MappedFileSource;

import java.util.Iterator;
import java.util.Map;
import java.util.TreeMap;
import java.util.regex.Pattern;

/** Разведка: какие сообщения, события и свойства сущностей есть в реплее. */
@UsesEntities
public class Explore {

    private final Map<String, Integer> messages = new TreeMap<>();
    private final Map<String, Integer> events = new TreeMap<>();
    private final Map<String, Integer> dtNames = new TreeMap<>();
    private final Map<String, String> samples = new TreeMap<>();
    private Context lastCtx;

    @OnMessage
    public void onMessage(Context ctx, GeneratedMessage msg) {
        String name = msg.getClass().getSimpleName();
        int n = messages.merge(name, 1, Integer::sum);
        if (msg instanceof skadistats.clarity.wire.dota.common.proto.DOTAUserMessages.CDOTAUserMsg_SpectatorPlayerUnitOrders o
                && (n % 3000 == 1)) {
            Entity u = ctx.getProcessor(Entities.class).getByIndex(o.getEntindex());
            System.out.println("ORDER tick " + ctx.getTick() + " ent " + o.getEntindex() + " type " + o.getOrderType()
                    + " -> " + (u == null ? "null" : u.getDtClass().getDtName()));
            if (u != null) dump(u, Pattern.compile("(?i)playerid|owner|controller"));
        }
        if (n <= 2 && name.matches("(?i).*(Order|Spectator|Behavior|Score|Chat|Ping|Click|Player).*")) {
            String s = msg.toString().replace('\n', ' ');
            samples.put(name + "#" + n, "tick " + ctx.getTick() + ": " + (s.length() > 400 ? s.substring(0, 400) : s));
        }
    }

    @OnGameEvent
    public void onGameEvent(GameEvent e) {
        events.merge(e.getName(), 1, Integer::sum);
    }

    private boolean midDumped = false;

    @OnTickEnd
    public void onTickEnd(Context ctx, boolean synthetic) {
        lastCtx = ctx;
        if (!midDumped && ctx.getTick() >= 30000) {
            midDumped = true;
            System.out.println("== mid-game controller and hero props (tick " + ctx.getTick() + ")");
            ctx.getProcessor(Entities.class).stream()
                    .filter(e -> e.getIndex() == 3 || e.getDtClass().getDtName().equals("CDOTA_Unit_Hero_Silencer"))
                    .forEach(e -> dump(e, Pattern.compile(".")));
        }
    }

    public static void run(String path, String keywordRegex) throws Exception {
        Explore ex = new Explore();
        try (var source = new MappedFileSource(path)) {
            new SimpleRunner(source).runWith(ex);
        }
        System.out.println("== messages");
        ex.messages.forEach((k, v) -> System.out.println(v + "\t" + k));
        System.out.println("== game events");
        ex.events.forEach((k, v) -> System.out.println(v + "\t" + k));
        System.out.println("== samples");
        ex.samples.forEach((k, v) -> System.out.println(k + "\t" + v));

        Entities entities = ex.lastCtx.getProcessor(Entities.class);
        Pattern kw = Pattern.compile(keywordRegex);
        entities.stream().forEach(e -> ex.dtNames.merge(e.getDtClass().getDtName(), 1, Integer::sum));
        System.out.println("== entity classes at end (" + ex.dtNames.size() + ")");
        ex.dtNames.forEach((k, v) -> {
            if (k.matches("(?i).*(Player|Data|Gamerules|Team|Spectator|Tower|Barracks|Fort|Ward|Healer|Building|Effigy|Watch|Lantern|Outpost).*")) System.out.println(v + "\t" + k);
        });
        System.out.println("== matching properties");
        entities.stream()
                .filter(e -> e.getDtClass().getDtName().matches("(?i).*(PlayerResource|DataRadiant|DataDire|DataSpectator|Gamerules|PlayerController).*"))
                .forEach(e -> dump(e, kw));
    }

    private static void dump(Entity e, Pattern kw) {
        Iterator<FieldPath> it = e.getState().fieldPathIterator();
        int shown = 0;
        while (it.hasNext() && shown < 400) {
            FieldPath fp = it.next();
            String name = e.getNameForFieldPath(fp);
            if (name != null && kw.matcher(name).find()) {
                System.out.println(e.getDtClass().getDtName() + "[" + e.getIndex() + "] " + name + " = " + e.getPropertyForFieldPath(fp));
                shown++;
            }
        }
    }
}
