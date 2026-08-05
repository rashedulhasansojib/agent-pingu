# A real Claude Code session, recorded live with vhs.
#
#   vhs assets/resume.tape
#
# Headless (`claude -p`) rather than the interactive TUI, deliberately: the TUI
# welcome panel shows the signed-in account and organisation, which does not
# belong in a public README. This is the same session either way.
#
# Re-record when behaviour changes — a recording cannot notice that it has gone
# stale. DEMO_REPO must be a repo with a filled-in vault.

Output "assets/resume.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1180
Set Height 560
Set Padding 20
Set TypingSpeed 55ms

Hide
Type "cd ${DEMO_REPO} && clear"
Enter
Sleep 1s
Show

Type "claude -p 'where are we?'"
Sleep 600ms
Enter
Sleep 75s          # a real session takes as long as it takes
Sleep 3s
