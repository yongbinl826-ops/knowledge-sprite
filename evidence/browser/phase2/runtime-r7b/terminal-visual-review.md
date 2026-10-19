# Actual terminal UI review — r7b PID16148

This review uses actual existing results, not mocked responses. Browser writes were blocked; no search, analysis, retry, or version creation was performed.

Frozen frontend: 84 browser regression cases passed previously, 45 Node tests passed, build passed; the 44-file source/dist manifest remains unchanged. Actual HTTP JavaScript SHA: `1ab294a8203868e60bb0f66ba6aa42df3c8bfe696a28ff6c6f21128cc4287501`.

## Observed and visually opened

| Case | Actual version | Observation window UTC | Findings |
| --- | --- | --- | --- |
| bicycle_csv_advanced | 5 | 19:33:32–19:33:46 | 7 units, 13 cards. Partial support remains separated from missing targets; two terminal empty units ask the learner to adjust goals rather than wait. |
| pygame_maze_intermediate | 5 | 19:35:11–19:35:24 | 6 units, 0 cards. Clear missing skills, next step, independent project exercise, and platform-search fallback. No loading state remains. |
| web_pomodoro_beginner | 4 | 19:37:46–19:37:52; card supplement 19:38:46–19:39:02 | 7 units, 4 partial cards. Timestamp and keyboard requirements remain unknown; displayed course support is qualified. |
| arduino_reaction_beginner | 4 | 19:39:16–19:39:22 | 5 units, 1 partial card. Serial monitor debugging is supported separately from INPUT_PULLUP/digitalRead unknown targets. |
| study_room_streamlit_intermediate | 1 | 19:41:33–19:41:39 | 6 units, 6 partial cards. File upload partial evidence remains separate from rerunning, validation and project-specific calculations. |

All three widths (1440, 768, 390) have document width equal to the viewport. Three local workflow steps were captured at each width. Keyboard Enter returns to knowledge review and results; eight Tab stops show visible focus. No console/runtime errors, blocked write attempts, or changed job IDs were recorded.

Actually opened screenshots:

- `terminal-data-v5/bicycle_csv_advanced/desktop-results-top.png`
- `terminal-data-v5/bicycle_csv_advanced/desktop-project-input.png`
- `terminal-data-v5/bicycle_csv_advanced/tablet-actual-course.png`
- `terminal-data-v5/bicycle_csv_advanced/tablet-knowledge-review.png`
- `terminal-data-v5/bicycle_csv_advanced/mobile-project-input.png`
- `terminal-data-v5/bicycle_csv_advanced/mobile-results-top.png`
- `terminal-data-v5/bicycle_csv_advanced/mobile-terminal-empty.png`
- `terminal-data-v5/bicycle_csv_advanced/desktop-keyboard-review.png`
- `terminal-maze-v5/pygame_maze_intermediate/desktop-results-top.png`
- `terminal-maze-v5/pygame_maze_intermediate/tablet-terminal-empty.png`
- `terminal-maze-v5/pygame_maze_intermediate/mobile-terminal-empty.png`
- `terminal-web-v4/web_pomodoro_beginner/desktop-results-top.png`
- `terminal-web-v4/web_pomodoro_beginner/tablet-knowledge-review.png`
- `terminal-web-v4/web_pomodoro_beginner/mobile-terminal-empty.png`
- `terminal-web-v4-cards/web_pomodoro_beginner/{desktop,tablet,mobile}-actual-course.png`
- `terminal-arduino-v4/arduino_reaction_beginner/desktop-actual-course.png`
- `terminal-arduino-v4/arduino_reaction_beginner/tablet-coverage-gap.png`
- `terminal-arduino-v4/arduino_reaction_beginner/mobile-terminal-empty.png`
- `terminal-streamlit-v1/study_room_streamlit_intermediate/desktop-results-top.png`
- `terminal-streamlit-v1/study_room_streamlit_intermediate/{tablet,mobile}-actual-course.png`
- `terminal-streamlit-v1/study_room_streamlit_intermediate/mobile-terminal-empty.png`

No new high/medium rendering or interaction defect was observed in these five cases. The earlier tablet blank-paint region did not reproduce with the actual final bundle; no CSS change was made. The first web observation focused a gap unit without cards; the evidence-only capture helper now independently selects a populated unit for course screenshots. Its supplement is stored separately and does not overwrite that first report.

A low-priority readability issue remains: exact text `状态对象` appears in two independently identified rows (title decomposition and a confirmed target), and `脚本重运行` is similarly duplicated in a missing list. This can duplicate the display count. An unintegrated exact-text conservative projection and eight passing Node tests are staged in `tmp/coverage-display-proposal/` for root review. Every underlying row/ID is retained; any unknown member remains unknown, and different wording never merges. No production file or bundle changed.

## Scope and pending work

The evidence confirms honest rendering of the received results, not complete teaching coverage, video playback, successful learning, or production readiness. Data remains partial and Maze has no courses. Actual error notices were not observed; the separate mock regression contains error/loading scenarios.

All five r7b terminal cases now have read-only UI observations. This does not certify a future r8 reload. Production content acceptance remains false: all projects are partial and Maze has no courses. Actual error notices were not observed; only the separately identified mock regression covers that state.
