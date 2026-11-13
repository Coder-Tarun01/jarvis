/* Wake-word phrase splitter (no DOM, no browser needed):
     node tests/wake_phrase_test.mjs                                              */
import { splitWakePhrase } from "../src/hooks/useWakeWord.js";

const cases = [
  ["hey jarvis", true, ""],
  ["Hey Jarvis, what's the weather?", true, "what's the weather?"],
  ["hello jarvis set a timer for five minutes", true, "set a timer for five minutes"],
  ["jarvis", true, ""],
  ["jarvis open antigravity", true, "open antigravity"],
  ["um hey jarvis", true, ""],
  ["what time is it", false, ""],
  ["", false, ""],
];

let failed = 0;
for (const [text, hit, rest] of cases) {
  const got = splitWakePhrase(text);
  const ok = got.hit === hit && got.rest === rest;
  if (!ok) failed += 1;
  console.log(`${ok ? "[ok  ]" : "[FAIL]"} ${JSON.stringify(text)} -> ${JSON.stringify(got)}`);
}
console.log(failed === 0 ? "wake splitter OK" : `${failed} FAILURE(S)`);
process.exit(failed === 0 ? 0 : 1);
