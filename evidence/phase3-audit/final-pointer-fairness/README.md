# Bounded related-topic pointer projection

Candidate only; stage was not edited. Copy only the files in `manifest.json`.

`service.py` changes only `results` plus three pure allocation helpers. Each
original skill keeps at most four candidates (six skills, at most 24 retained
entries). Fewer literal missing components ranks first, then stable URL/IDs.
Four display slots are assigned round-robin in original skill order with URL
deduplication. The full existing resource pool is scanned, but each producer
still contributes at most six candidates. No source, fetch, model or resource
budget increases. No teaching matches or coverage are created.

The real Arv4 failure had two causes. Taiji was searched for k2 analogRead, not
k5 analogWrite; an actual, current reviewed-empty decision already existed for
k5. The old same-point search guard excluded it before the first-four cutoff.
The initial failing test is preserved in `focused.xml`; no k5 search was invented.
The authorized minimal addition permits that existing decision to link only a
directory pointer after `validate_reviewed` successfully rebinds current point,
source and stage. This path explicitly skips primary ranking. `{}` sentinels,
unreviewed/old/changed/foreign-job records cannot use it.

`teaching_match.py` changes **only `topic_pointers`**. A bare all-uppercase
family/object acronym cannot alone admit a specific-method target. A non-family
method identifier or literal requested phrase must actually appear in the own
chapter heading. A target consisting only of its acronym retains that topic;
underscore constants remain distinct. No acronym/API name list is used. All
existing own-page/native URL, raw quote/hash and scope validators are unchanged.

Offline retained-source replay:

- Arv4: four skill-2 PWM pointers become two useful pointers, starting with the
  actual skill-1 `analogWrite` original p26 heading and URL, then the remaining
  skill-2 digital-pin heading. Full raw catalog SHA is preserved.
- Webv5: four DOM-family/offset pointers are removed because they do not name
  selector queries or cached references.
- Every field other than `related_topic_pointers` is exactly equal before/after
  in both complete JSON projections. Match counts remain 0/0/0. Read DB writes,
  HTTP, model and search calls are zero. This is a pure replay, not new live work.

`actual-before.json` and `actual-after.json` preserve full projected outputs.
`report.json` records source bindings, scope of the changes, test counts and
byte hashes. The previous mocked cap test reused one URL across six resources;
its single fixture-line migration now uses each pre-existing canonical URL,
preserving all original assertions while independently testing the cap.
