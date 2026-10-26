# Echo VR mod template

Start here to make a mod for Echo VR that players can get from the
[Echo VR launcher](https://github.com/marshmallow-mia/EchoVR_Launcher). A mod is a small
Windows DLL that the game's mod runtime, [nEVR](https://github.com/EchoTools/nevr-runtime),
loads when Echo VR starts. On Linux the same DLL runs under Proton.

This template gives you a mod that already loads and logs, a build that works from Linux,
macOS and Windows, and GitHub Actions that check every push and turn a version tag into a draft
release that the project signs and publishes.

> Working with an AI agent? Point it at [AGENTS.md](AGENTS.md): it has the exact rules and
> formats. This README only covers the basics.

## 1. Make it yours

1. Click **Use this template** on GitHub, then clone your new repo.
2. Open `echo-mod.json` and change:
   - `id`: a short lowercase name, unique among all mods (`my-cool-mod`)
   - `name`, `summary`, `author`
   - `file`: your DLL's name (`MyCoolMod.dll`). Rename `ExampleMod.plugin.json` to match
     (`MyCoolMod.plugin.json`) and change `settings` to that name.
   - `capabilities`: what your mod does (see below). Be honest: players see them.
   - `license`: keep MIT or pick another open-source license, and change `LICENSE` to match
     (put your name in it).
3. Say whose work you build on. Put the people and projects you took code, addresses or ideas
   from in your README and in `NOTICE` (it travels with your DLL), with their licence, and give
   anyone whose code or findings a commit uses a `Co-Authored-By:` line in that commit
   ([AGENTS.md](AGENTS.md#credit) has the format).
4. Write your mod in `src/mod.cpp`. The rest of `src/` is plumbing you rarely need to touch.

Everything else (the DLL's name, its version, what it tells nEVR) comes from `echo-mod.json`,
so that file is the only one to edit when you bump the version. Pick `id` and `file` with
care: once the mod is approved they stay (a new name needs the maintainers, on your
submission issue).

Does your mod need another one, or can't it run beside one? Say so in `requires` and
`conflicts` ([AGENTS.md](AGENTS.md#echo-modjson) has the format): the launcher installs what
it needs and keeps conflicting mods apart.

Before you push, run `just verify` (below). `python3 tools/check_mod.py` alone checks just
`echo-mod.json`, the way the launcher's catalogue will.

### Already started from an older copy of this template?

Your repo can take the template's newer tooling without touching your mod. Copy these from the
template into your repo, keep your own `echo-mod.json`, `LICENSE`, `README.md`, your settings
sheet, `src/mod.cpp` and any `ECHO_MOD_MINHOOK` default you changed in `CMakeLists.txt`, then run
`just fmt` and `just verify`:

- `justfile`, `.clang-format`, `NOTICE` (then fill in your credits)
- `tools/` and `tests/` (all of it)
- `.github/workflows/` (all three files: they replace your `release.yml` and `build.yml`)
- `src/plugin.cpp` and the other plumbing in `src/` (`args.cpp`, `game.cpp`, `hooks.*`, `log.cpp`,
  `mod.h`)
- `CMakeLists.txt`: take the template's and set `option(ECHO_MOD_MINHOOK ... ON)` again if your mod
  hooks the game

Then `git diff` the result: the only changes outside your own files should be the template's.

### Capabilities

| Capability | Your mod... |
|---|---|
| `observes-only` | only reads the game (stats, overlays that show data) |
| `cosmetic` | changes looks or sound only |
| `alters-gameplay` | changes physics, weapons, movement |
| `alters-rules` | changes match rules, scoring or the game mode |
| `network` | talks to the internet or opens sockets |
| `hooks-engine` | hooks the game's functions itself (needed with MinHook) |

## 2. Build it

**Easiest: let GitHub build it.** Every push runs the **build** workflow. Its result (the
**Artifacts** of the run, under **Actions**) is your DLL.

**On your PC** you need CMake 3.20+, Ninja and MinGW-w64:

- Linux: install `mingw-w64`, `cmake`, `ninja` (Ubuntu: `sudo apt install mingw-w64 cmake ninja-build`)
- macOS: `brew install mingw-w64 cmake ninja`
- Windows: [MSYS2](https://www.msys2.org/) with `mingw-w64-x86_64-toolchain`, `cmake`, `ninja`,
  or Visual Studio (use the `msvc` preset from a *x64 Native Tools* prompt)

```sh
cmake --preset mingw
cmake --build --preset mingw        # -> build/mingw/ExampleMod.dll
```

On Linux, `just verify` runs the same gate as GitHub: formatting (`.clang-format`), lint, a build
with warnings as errors, a smoke test that loads your DLL under Wine, the release checks and the
tests. It needs `just`, MinGW-w64, CMake, Ninja, Wine, `clang-format` and `shellcheck`. If it says
a file needs formatting, `just fmt` fixes it. `just --list` shows the smaller steps.

Your DLL carries a build stamp (`NEVR-PLUGIN-BUILD <version> <commit>`) that the signing step
checks against your tag. You don't edit it; it comes from `echo-mod.json` and git.

### Hooking the game

If your mod hooks or patches the game (it then needs the `hooks-engine` capability and
`-DECHO_MOD_MINHOOK=ON`, or `option(ECHO_MOD_MINHOOK ... ON)` in `CMakeLists.txt`):

- Check the bytes before you touch anything (`hooks::Hook` does), and never hook a function nEVR
  hooks itself.
- Prefer a hook that says in readable code what the original did and what you change over a byte
  patch.
- If the addresses or the idea come from another project's patch, work out for yourself what the
  patched code does before you build yours, write it down, and credit them (step 3 of section 1). Their
  address list says where to look; it isn't your design.

The full rules are in [AGENTS.md](AGENTS.md#rules-all-of-them-are-checked-or-reviewed).

## 3. Try it in the game

Testing goes in steps, each reaching more people:

1. **On your PC:** turn on local plugins for the version you test with (the launcher's guide:
   [Writing a plugin and loading it from your PC](https://github.com/marshmallow-mia/EchoVR_Launcher/blob/main/docs/plugins/local-plugins.md#4-loading-it-with-the-launcher)),
   then **Mods → Installed mods → Add DLL**, pick your DLL (with its `.plugin.json` beside
   it), start with **PLAY**. Your mod's state (Loaded, Failed and why) is on the Mods page;
   **Logs** opens its log. After a rebuild, add the DLL again.
2. **Your testers:** once your first mod is approved you have a **dev channel** (below):
   upload a test build there, and your testers see it in their launcher.
3. **Everyone who wants to:** release a prerelease (`1.5.0-beta.1`). Players get it only if
   they turn on prereleases for your mod.
4. **Everyone:** release it.

## 4. Publish it

**Releases come from GitHub, built by the release workflow, and signed by the project.** You
never upload a DLL yourself, and nobody edits a release by hand.

1. Set `version` in `echo-mod.json`. Versions are [semantic versions](https://semver.org/):
   `1.4.2`. A version with a prerelease part (`1.5.0-beta.1`) is published as a prerelease:
   players only get it if they choose to try your mod's prereleases.
2. Run `just verify`, commit, then tag that commit with the version, prefixed with `v`, and push
   the tag:
   ```sh
   git tag v1.4.2 && git push origin v1.4.2
   ```
3. The **release** workflow builds, smoke-tests and checks the release by the launcher's rules, then
   attests the files (a record that shows they were built here, from this tag) and opens a
   **draft** release with three files: `<id>-v<version>-windows.zip` (your DLL, `LICENSE`, `NOTICE`
   and settings sheet), `echo-mod.json` and `SHA256SUMS`. If something's off (the tag doesn't match
   `echo-mod.json`, say), it stops and tells you, and no draft is made.

A draft is not live: players can't see it. That is how a release reaches signing:

- **Your repo is where you work.** Players' launchers take a mod from a copy of your repo that the
  EchoTools maintainers own, because only releases built there are signed. Your changes get into the
  copy through a pull request from your repo, which a maintainer reads (what changed since the last
  signed version, and the build files) and merges. Only maintainers tag the copy.
- **A maintainer tags the copy**, its release workflow builds the draft, and the project owner checks
  that the draft is exactly what was reviewed. Then the release signer signs the DLL inside the zip,
  replaces it in the draft and publishes the release.
- **Then the launcher picks it up** within about 5 minutes, and the result (live, or why not) is
  posted on your submission issue.

Expect the same day to a few days per version: the builds take minutes, the reading and the signing
are done by people. A version, once published, never changes: fix things with a new version.
Something seriously wrong with a published version? Comment on your submission issue (or use the
**Pull a version** form in echo-mods): it can be turned off for everyone, and players go back to the
version before.

Testing your own build comes before all of that: section 3 above (your PC, your testers, a
prerelease).

### Getting into the launcher

- **Your first mod:** open a submission at
  [EchoTools/echo-mods](https://github.com/EchoTools/echo-mods/issues/new/choose) once your repo
  has a release. The form asks for your EchoVRCE username, so the maintainers know who you are
  there: like everything in the issue, it's public. An automatic check runs and comments on it. When
  the mod is approved, the maintainers make the EchoTools copy of your repo (above), and from then
  on every new version goes through the steps above.
- **After the first approval** you also get a **dev channel**: a folder you upload test builds
  to over SFTP (with your GitHub account's SSH keys), and a code (in `DEV-CODE.txt` there).
  In the launcher the code works for your EchoVRCE account and the testers you list in
  `access.json` in that folder by their **EchoVRCE account IDs** (they copy theirs on the
  launcher's EchoVRCE page, **Copy ID**; usernames don't count, as names can change):
  `{"schema": 1, "accounts": ["8f0c…-…", "…"]}`. `ACCESS-STATUS.txt` beside it says what was found.
- **Each new mod** of yours is submitted once the same way.

### Who sees your mod

Set `visibility` in `echo-mod.json`:

- `public` (the default): listed in the launcher for everyone
- `unlisted`: not listed; anyone who knows its id adds it (More mods → **Add by id**)
- `private`: like unlisted, but only for you and the accounts in your dev channel's
  `access.json` (above), signed in with EchoVRCE

The newest release (not a prerelease) decides.

## Rules

- No cheats, and nothing that gives an unfair advantage in public matches.
- No collecting players' data. Network use is declared with the `network` capability.
- Capabilities are honest.
- The source is public and under an open-source license: the launcher redistributes your
  files, so it needs the right to. Keep the licence of anything you copy, and credit it.
- Mods are for Echo VR on PC (Windows, and Linux through Proton).

Antivirus programs sometimes flag new, unknown DLLs. If yours is, tell us; don't ask players
to turn their antivirus off.

## Need help?

Ask in the Echo VR community Discord, or open an issue in
[EchoTools/echo-mods](https://github.com/EchoTools/echo-mods/issues).
