package ruiner;

public class Main {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: parse <replay.dem> | explore <replay.dem> [regex]");
            System.exit(2);
        }
        switch (args[0]) {
            case "parse" -> Parse.run(args[1], args.length > 2 ? args[2] : null);
            case "changes" -> ExploreChanges.run(args[1]);
            case "explore" -> Explore.run(args[1], args.length > 2 ? args[2] : "(?i)behav|conduct|comm|report|scoreboard|afk|idle|order|abandon");
            default -> {
                System.err.println("unknown command " + args[0]);
                System.exit(2);
            }
        }
    }
}
