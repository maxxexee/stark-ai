/**
 * Matches contractions the way recognizers write them ("that's", "thats", "that is"), including
 * the curly apostrophe Safari returns.
 */
export class SleepIntent {
  private static readonly WHOLE = new RegExp(
    "^(?:(?:hey|hi|ok|okay|yo|so|no|thanks|thank\\s+you)[,\\s]+)*" +
      "(?:stark[,\\s]+)?" +
      "(?:you\\s+can\\s+)?" +
      "(?:" +
      "go\\s+to\\s+sleep|stop\\s+listening|sleep" +
      "|(?:that\\s*['’]?s|that\\s+is)\\s+(?:all|it)" +
      "|goodbye|bye|(?:i\\s*['’]?m|i\\s+am)\\s+done" +
      ")" +
      "(?:[,\\s]+(?:now|please|thanks|thank\\s+you))*[.!]*$",
    "i",
  );

  private static readonly ANYWHERE = new RegExp(
    "\\b(?:" +
      "go\\s+to\\s+sleep|stop\\s+listening" +
      "|(?:that\\s*['’]?s|that\\s+is|that\\s+will\\s+be)\\s+(?:all|it|enough)" +
      "|good\\s*bye|goodbye|bye" +
      "|(?:i\\s*['’]?m|i\\s+am)\\s+done" +
      "|(?:i\\s*['’]?ve|i\\s+have)\\s+had\\s+enough" +
      "|(?:i\\s+)?(?:don['’]?t|do\\s+not)\\s+need\\s+(?:your\\s+)?help" +
      ")\\b",
    "i",
  );

  static matches(text: string): boolean {
    const said = text.trim().replace(/\s+/g, " ");
    return SleepIntent.WHOLE.test(said) || SleepIntent.ANYWHERE.test(said);
  }
}
