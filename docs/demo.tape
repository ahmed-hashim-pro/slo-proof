# Terminal demo for the README. Regenerate with:  make demo
# Runs the real CLI on the committed example month; nothing is staged.

Output docs/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1180
Set Height 560
Set Padding 18
Set Theme "GitHub Dark"
Set TypingSpeed 30ms

Hide
Type "export PYTHONPATH=/vhs/src PS1='$ ' && alias slo-proof='python3 -m slo_proof' && cd /vhs && clear"
Enter
Show

Type "slo-proof compare examples/sli.csv examples/incidents.csv examples/rules.toml"
Enter
Sleep 7s

Type "clear"
Enter
Sleep 300ms

Type "slo-proof replay examples/sli.csv examples/incidents.csv examples/rules.toml --rule fast-burn-only --fail-on-miss"
Enter
Sleep 5s

Type "echo exit $?"
Enter
Sleep 3s
