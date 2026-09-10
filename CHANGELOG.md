# Changelog

Milestones only.

## 0.1.0

- First version. Weekly (and on demand) it moves the pins its policy allows, republishes the
  binaries those pins cover, proves the result with the controller's release-verification lane,
  releases a patch and cuts the image — or releases nothing and says why.
- The daemon, RadioLib and the shared chat source are reported, never moved: the lab retargets
  them at fakes, so a moved pin would not be exercised at all.
- The Meshtastic web client and CLI ARE moved. Either move forces the Meshtastic binary to be
  republished: the client ships inside that artifact, and the CLI's recorded version ships in the
  completion marker that artifact carries, even though the venv itself is built on the box.
- A pin can be frozen: one reason string in `policy.toml` holds that input while everything else
  keeps releasing. Refused where it would hold nothing, and never expiring on its own.
- The bot freezes a stack itself when the lane's evidence names it as the one that failed, opens
  an incident and retries once. It acts on an explicit per-stack assertion, never on a job name
  or a case name, and refuses whenever the hold would be a guess.
- A run that published anything records it in an `attempt` issue here, which outlives the run
  and blocks the next release until the attempt is finished or undone.
