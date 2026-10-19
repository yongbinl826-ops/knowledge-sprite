r7 full independent backend regression did not fully pass: **2676 passed, 3 failed, 26 subtests passed**, 1 existing Starlette deprecation warning, 71.85 s.

All three failures are in `tests/test_project_search_context.py` (lines 28 and 48): old expected search names omit the new owner/CJK separator. Actual canonical names are `pygame 键盘移动`, `pygame 初始化`, `C++ 对象与构造`. `project_search.py:47` calls the new `canonical_search_name`; `tests/test_technical_prefix.py:32–42` independently confirms canonical search/target keys while preserving the original point/display/concepts.

The review changed neither production source nor assertions. Root should resolve this search-name contract mismatch and repeat the full regression. No CSS, Clock, source raw/probe, technical-prefix or cache boundary test failed. This run is not reported as a pass.

Start/end manifests cover all 132 backend/test Python files. Tree SHA `4aef7ae9bb961785fe417f32f73cf993f11721ea867bd6ed784877b18ae0e2f8` was identical before/after; all 34 integrated source/fixture hashes matched. Dotenv and pyc were disabled; DB/cache/basetemp and OS temp were under `tmp/backend-final-r7`. The existing service process was untouched.

Evidence: `backend-final-r7.xml`, `backend-final-r7-start.json`, `backend-final-r7-end.json`, `backend-final-r7-independent-review.json`.
