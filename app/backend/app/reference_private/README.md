# reference_private

Reference material that belongs to a particular event organiser or client
rather than to this application: lists of space names read from their
accommodation matrices, their naming structure for network rooms, and the
like. It is **not part of the published source** — the folder is ignored by
git and left out of a public package (`tools/make_package.py --public`) —
because it is the client's material, not the author's.

The application works without it:

* `aam_names.txt` — `<functional area>\t<space name>` per line. When present,
  a room-name label on a sheet that prints no space code is kept only when it
  reads like one of these names (or like a name the project's own TEAP
  carries). When absent, the project's TEAP names alone make the vocabulary.
* `naming_reference.json` — the naming table shown in the *Naming* side panel
  of the Drawing viewer and the NERs screen. When absent, the panel shows the
  application's own naming rule and nothing else. It never decides a name.

Put the files here before building a package for a team that is entitled to
them.
