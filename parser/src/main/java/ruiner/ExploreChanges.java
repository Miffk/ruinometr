package ruiner;

import skadistats.clarity.model.Entity;
import skadistats.clarity.model.FieldPath;
import skadistats.clarity.processor.entities.OnEntityPropertyChanged;
import skadistats.clarity.processor.entities.UsesEntities;
import skadistats.clarity.processor.runner.Context;
import skadistats.clarity.processor.runner.SimpleRunner;
import skadistats.clarity.source.MappedFileSource;

import java.util.Map;
import java.util.TreeMap;

/** Разведка: какие свойства контроллеров игроков вообще меняются за матч и сколько раз. */
@UsesEntities
public class ExploreChanges {

    private final Map<String, int[]> counts = new TreeMap<>();

    @OnEntityPropertyChanged(classPattern = "CDOTAPlayerController")
    public void onChange(Context ctx, Entity e, FieldPath fp) {
        int p = Parse.playerOf(e);
        if (p < 0) return;
        String name = e.getNameForFieldPath(fp);
        counts.computeIfAbsent(name, k -> new int[Parse.PLAYERS])[p]++;
    }

    public static void run(String path) throws Exception {
        ExploreChanges ex = new ExploreChanges();
        try (var source = new MappedFileSource(path)) {
            new SimpleRunner(source).runWith(ex);
        }
        ex.counts.forEach((k, v) -> {
            StringBuilder sb = new StringBuilder(k);
            for (int c : v) sb.append('\t').append(c);
            System.out.println(sb);
        });
    }
}
