Maze v6 independent source review
=================================

Actual result remains partial: 1/6 units, one partial card, zero complete collections, 106.401391 seconds. First useful card arrived at ~100.983 seconds. This is not production coverage acceptance.

| Unit | Actual useful source | Independent finding |
|---|---|---|
| k1 map | None | 20x20 line grid / standalone Rect do not establish 2D-list wall/road/exit map or requested combined APIs. |
| k2 movement/walls | None | Hit boxes and snake body positions do not establish destination-cell walls or 0..7 bounds. |
| k3 keyboard edge | None | Generic keyboard/held movement does not establish KEYDOWN once versus get_pressed or four-arrow mapping. |
| k4 states/win | None | **Software false negative:** own Scoring lesson proves font/render/blit, but `pygame.font 渲染文字` misses the target-shape matcher. No state/win evidence is inferred. |
| k5 R/Esc loop | None | Q exit, generic loops and snake collision reset do not prove requested R/Esc and WIN behavior. |
| k6 timing/FPS | Snake Tutorial #1 | Honest partial: clock.tick only. get_ticks/elapsed/reset remain unknown. |

All six TWT attempts actually use v3 and 3 cached public indexes/2 observed series. Four-target hashes match. All six-candidate provider orders survive ingestion. Clock own job obtains Movement0/Snake1; Scoring0 is now fetched for k4. Thus r7 series-selection and same-job Clock association gaps are genuinely closed. Source facts were cache hits with original timestamps, not new directory fetches. Full queue start traces are not persisted; do not overstate start ordering from final metadata.

The confirmed font miss is in `ranking.py:407-409`, before existing same-own-source Font→render→blit proof. Pure retained replay: actual target false / helper not applicable; equivalent `pygame 文字显示` true; no nonteaching veto; binding valid. A temporary-only correction is being prepared separately. It is **not** part of this actual result.

Zero new HTTP/model requests; read-only SQLite URI + query_only used; no source/test/database changes. Original r7 failures and v6 output remain intact.
