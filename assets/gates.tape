# The verify gate, run for real.
#
#   vhs assets/gates.tape
#
# `--execute` runs the suite and the gate still refuses, because the check no
# tool can decide is outstanding. That is the sequence worth showing.

Output "assets/gates.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 560
Set Padding 20
Set TypingSpeed 45ms

Hide
Type "cd ${DEMO_REPO} && export PATH=${PINGU_BIN}:$PATH && clear"
Enter
Sleep 1s
Show

Type "pingu status"
Sleep 400ms
Enter
Sleep 2s

Type "pingu gate verify"
Sleep 400ms
Enter
Sleep 2.5s

Type "pingu gate verify --execute"
Sleep 400ms
Enter
Sleep 4s
Sleep 2s
