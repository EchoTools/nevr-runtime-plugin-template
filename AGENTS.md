# AGENTS.md: building an Echo VR mod from this template

This file is for coding agents, and for anyone who wants the exact contract. The README is the
short version for people.

A **mod** is an x64 Windows DLL that nEVR (the game's mod runtime, `bin/win10/BugSplat64.dll`)
loads into `echovr.exe` build 631547. The Echo VR launcher installs mods, writes nEVR's config,
and only loads mods it can verify. Everything below has to hold, or the launcher won't take the
mod, or nEVR won't load it.

## Repo layout

| Path | What it is | Edit? |
|---|---|---|
| `echo-mod.json` | The manifest: the single source of the mod's id, name, file, version, capabilities | yes |
| `src/mod.cpp` | The mod itself: `Start`, `Frame`, `StateChanged`, `Stop` | yes |
| `src/mod.h` | What the template gives the mod: logging, args, game checks, runtime exports | add to it |
| `src/plugin.cpp` | The nEVR exports; calls `mod::*` | rarely |
| `src/log.cpp`, `src/args.cpp`, `src/game.cpp` | The helpers from `mod.h` | rarely |
| `src/hooks.cpp`, `src/hooks.h` | MinHook detours, built only with `-DECHO_MOD_MINHOOK=ON` | rarely |
| `src/exports.def` | Exactly the exports the DLL has | no |
| `include/nevr_plugin_interface.h` | The nEVR plugin ABI, v7: a copy of nevr-runtime's header (commit in its top comment), plus the template's `NEVR_CTX_HAS` | **never** hand-edit: re-copy from nevr-runtime |
| `include/plugin_assets.h` | Plugin-asset wrappers (API v7): `nevr::RegisterAsset`, `nevr::DeregisterAssets`. A copy of nevr-runtime's | **never** hand-edit: re-copy |
| `examples/assets/asset_example.cpp` | Registers one plugin-carried asset, off by default (`-DECHO_MOD_ASSET_EXAMPLE=ON`, needs `"api": 7`) | example, not built by default |
| `<Stem>.plugin.json` | The settings the launcher shows for the mod | yes |
| `tools/check_mod.py` | The checks the release and the echo-mods review run | **never** weaken |
| `tools/package.py` | Packs a release into `dist/` | no |
| `tools/ci-build.sh` | Build + Wine smoke test + checks | no |
| `tools/check_pr_title.py` | Checks a PR title is a Conventional Commits header | no |
| `tests/smoke_host.c` | Loads the DLL like nEVR and calls its exports | no |
| `tests/test_check_mod.py`, `tests/test_check_pr_title.py` | Tests of the checks themselves | add to them |
| `justfile` | `just verify` and the recipes under it | rarely |
| `.clang-format` | The code style (4 spaces, 120 columns); `just fmt` applies it | no |
| `NOTICE` | Credits and notices that travel with the DLL in the release zip | yes |
| `.github/workflows/release.yml` | Builds, attests and drafts releases (the release signer publishes them) | **never** |
| `.github/workflows/build.yml` | Format, lint, build, smoke test, checks and tests on every push | no |
| `.github/workflows/pr-title-check.yml` | Fails a PR whose title isn't a Conventional Commits header | no |

The launcher and the release signer only take release files built and attested by this repo's
unmodified `release.yml`. Don't edit it, don't rename it, don't attach files to a release by hand.

## Commands

```sh
just verify       # the whole gate: lint, check, test (Linux: MinGW-w64, CMake, Ninja, Wine, clang-format, shellcheck)
just build        # build/mingw/<file>.dll, warnings are errors
just check        # build, Wine smoke test, manifest + DLL checks, then pack a release and check that
just test         # the tests of the checks
just lint         # clang-format check, shellcheck, Python compile
just fmt          # apply .clang-format
```

Without `just`: `cmake --preset mingw && cmake --build --preset mingw`, then
`python3 tools/check_mod.py --dll build/mingw/<file>.dll`; `tools/ci-build.sh` does the build, the
smoke test and the checks. With MinHook:
`cmake -S . -B build/mh -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/mingw-toolchain.cmake -DECHO_MOD_MINHOOK=ON`.
With the plugin-asset example (needs `"api": 7`):
`cmake -S . -B build/assets -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/mingw-toolchain.cmake -DECHO_MOD_ASSET_EXAMPLE=ON`.

A change is done when `just verify` passes (or the **build** workflow on GitHub, which runs the
same steps).

## echo-mod.json

```json
{
  "schema": 1,
  "id": "example-mod",
  "name": "Example mod",
  "summary": "One line for the launcher's list.",
  "author": "Your name",
  "version": "0.1.0",
  "kind": "mod",
  "file": "ExampleMod.dll",
  "api": 5,
  "capabilities": ["observes-only"],
  "target": "client",
  "visibility": "public",
  "requires": { "nevr": ">=4.1.0", "mods": [] },
  "conflicts": [],
  "license": "MIT",
  "homepage": "",
  "args": {},
  "settings": "ExampleMod.plugin.json"
}
```

| Field | Rule |
|---|---|
| `schema` | `1` |
| `id` | `^[a-z0-9][a-z0-9._-]{0,63}$`, unique among all mods, never changes after approval. Reserved: the launcher's own mods (`asset-patches`, `xmlhttp-fix`, `gpu-rating`, `content-overlay`, `missing-textures`, `server-patches`, `echocombat`) and everything starting with `nevr`, `echoxr` or `echotools` |
| `name`, `summary`, `author` | Non-empty text |
| `version` | A [semantic version](https://semver.org/): `MAJOR.MINOR.PATCH`, optional `-prerelease`, optional `+build`. No `v` here. A prerelease part makes the release a prerelease. Build metadata doesn't count when versions are compared, so `1.0.0+a` and `1.0.0+b` are the same version |
| `kind` | `mod` (one DLL); `pack` (DLL + content, below) isn't published yet |
| `file` | `^[A-Za-z0-9._-]{1,64}\.dll$`, unique among all mods, never changes after approval (the maintainers can rename it). Reserved: `BugSplat64.dll`, `dbgcore.dll`, `nevr.dll`, `log_filter.dll`, the game's own DLLs, and every name starting with `Nvr`, `nEVR` or `EchoXR` (any case) |
| `api` | The plugin API version reported to nEVR: `5` (default, runs on every nEVR the launcher ships without a warning), `6`, or `7` (carries plugin assets, see below) |
| `capabilities` | At least one of `observes-only`, `cosmetic`, `alters-gameplay`, `alters-rules`, `network`, `hooks-engine`. `observes-only` stands alone. Importing a network DLL (`ws2_32`, `wininet`, `winhttp`, ...) needs `network`; installing hooks needs `hooks-engine` |
| `target` | `client` or `both` (`server`, game servers only, isn't published yet) |
| `visibility` | `public` (listed), `unlisted` (only by id: More mods → Add by id) or `private` (only the author's EchoVRCE account and the account IDs in their `access.json`). The newest release that isn't a prerelease decides |
| `requires.nevr` | A version range of nEVR: comparators `>=`, `>`, `<=`, `<`, `=`, `^`, `~`, space-separated (`>=4.1.0 <6.0.0`), or `*` |
| `requires.mods` | `[{"id": "other-mod", "version": ">=1.2.0"}]`: mods that must be on too |
| `conflicts` | Ids of mods that must not be on at the same time |
| `license` | An SPDX id of an open-source license (`MIT`, `Apache-2.0`, `GPL-3.0-only`, ...), matching `LICENSE` |
| `homepage` | Empty or `https://...` (the launcher links the repo itself) |
| `args` | Default options, an object (values become strings) |
| `settings` | Path of the `<Stem>.plugin.json` describing the mod's settings, or omitted |
| `required`, `shipped` | Not allowed: only for the launcher's own mods |

CMake reads `id`, `name`, `summary`, `version`, `file`, `api` and `capabilities` from this file
and passes them to the code as `MOD_ID`, `MOD_SUMMARY`, `MOD_VERSION`, `MOD_VERSION_MAJOR/MINOR/PATCH`,
`MOD_STEM` (file without `.dll`), `MOD_API` and `MOD_CAPABILITIES`. Never hard-code these in
the source: `check_mod.py` compares what the DLL reports with the manifest.

## The plugin ABI

nEVR loads a plugin only when the launcher lists it in `_local/config.yaml`; the file goes to
`bin/win10/plugins/<file>`. It loads it with
`LoadLibraryExA(path, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32)`,
looks up the exports by name, loads every plugin first, then calls the inits ordered by
capability (undeclared, observes-only, cosmetic, alters-gameplay, alters-rules, network,
hooks-engine), config order within each.

Exports (unmangled, `extern "C"`, listed in `src/exports.def`):

| Export | When | Contract |
|---|---|---|
| `NvrPluginInfo NvrPluginGetInfo(void)` | load | Required. Static strings only. `name` = the mod's id |
| `uint32_t NvrPluginGetApiVersion(void)` | load | `MOD_API`. Absent means 1 |
| `uint32_t NvrPluginGetCapabilities(void)` | load | The capability bits: observes-only 0x01, cosmetic 0x02, alters-gameplay 0x04, alters-rules 0x08, network 0x10, hooks-engine 0x20 |
| `int NvrPluginInitEx(const NvrGameContext*, const char* args_json)` | once, after all plugins loaded | 0 = keep me, non-zero = unload me. `args_json` is a flat JSON object of strings, `"{}"` when empty, never null |
| `int NvrPluginInit(const NvrGameContext*)` | once, only if there's no InitEx | Same, without args |
| `void NvrPluginOnFrame(const NvrGameContext*)` | every frame, game thread | Short, never blocks |
| `void NvrPluginOnGameStateChange(const NvrGameContext*, uint32_t old, uint32_t new)` | state changes | `ctx->net_game` valid once `flags & NEVR_HOST_HAS_NETGAME` |
| `void NvrPluginShutdown(void)` | clean unload, and right after a failed init | Not guaranteed at process exit. Without it, nEVR keeps a failed plugin loaded |

`NvrGameContext` grows only at its end. Read a field past `flags` only after
`NEVR_CTX_HAS(ctx, field)`:

| Fields | Since | nEVR |
|---|---|---|
| `base_addr`, `net_game`, `game_state`, `flags` | v1 | all |
| `ctx_size`, `get_plugin_count`, `get_plugin_info` | v5 | 4.1.0 (live servers), 5.2.x (launcher Beta) |
| `plugin_id`, `log` | v6 | 5.3.0 and newer |

Hosts before v5 aren't supported (no launcher ships one). Host flags: `HAS_NETGAME` 0x01,
`IS_SERVER` 0x02, `IS_CLIENT` 0x04, `COMBAT_MODE` 0x08, `IS_HEADLESS` 0x10.

EchoLoader 2 (used for EchoRelay servers and event builds) hosts the same ABI at v5, calls init
before the game's entry point (`net_game` always null, `game_state` 0), and copies the mod
beside its own plugins. A mod should work there too or return non-zero from init.

## Rules (all of them are checked or reviewed)

1. **`DllMain` only calls `DisableThreadLibraryCalls`.** No hooks, threads, files or logging
   there: the loader lock is held. Everything starts in `mod::Start`.
2. **Check the game build first.** `plugin.cpp` already returns non-zero unless `echovr.exe`'s PE
   timestamp is `0x6452DFF6` (build 631547). Keep that. Outside the game (the smoke host) init
   must return non-zero, cleanly.
3. **Check the bytes before patching or hooking** (`mod::BytesAt`, `hooks::Hook` does it). Leave
   anything that doesn't match alone, log it, and keep running or return false from `Start`.
4. **Never hook a function nEVR hooks itself.** nEVR re-checks its own hooks after every plugin's
   init; on a game server a hook over one of them ends the process. To change something nEVR
   already hooks, use what it offers (resource overrides below) instead.
5. **MinHook:** each DLL has its own copy. Treat `MH_ERROR_ALREADY_INITIALIZED` as success.
   Never call `MH_Uninitialize` or `MH_DisableHook(MH_ALL_HOOKS)`; remove only your own hooks
   (`hooks::End` does).
6. **Everything linked statically.** The DLL may import only Windows' own DLLs (`check_mod.py`
   has the list); no `libstdc++-6.dll`, `libgcc_s_seh-1.dll`, `libwinpthread-1.dll`,
   `vcruntime*.dll`, `msvcp*.dll`. MinGW: the toolchain file's `-static`. MSVC: `/MT` (set in
   `CMakeLists.txt`). No other DLLs beside it.
7. **Only the `Nvr*` exports** leave the DLL (`exports.def`, `--exclude-all-symbols`).
8. **Never log option values or secrets.** Log what you made of them (`log_states on`).
9. **Threads:** callbacks run on the game's thread. Slow work (files, network) goes on a thread
   started in `Start`, and stops in `Stop`.
10. **Log to `plugin_logs/<Stem>/<Stem>.log`** through `mod::Log`/`Warn`/`Error`; on v6 hosts it
    also reaches nEVR's log. That's where the launcher's Logs button and log upload look.
11. **Capabilities are honest** and match what the code does (rule above for network and hooks).
12. **No cheats, no data collection,** no network use beyond what the mod is for.
13. **Never write into the game's folders** except the mod's own log folder and a settings file
    the `.plugin.json` names. Never touch other plugins' files, `config.yaml`, or `BugSplat64.dll`.
14. **The DLL carries its build identity:** exactly one `\0NEVR-PLUGIN-BUILD <version> <commit>\0`
    literal (`src/plugin.cpp`; CMake fills in the version from `echo-mod.json` and the commit from
    `GITHUB_SHA`, or `git rev-parse HEAD` on your machine, or 40 zeros with no git). The release signer
    compares it with the tag and the commit that was built. Never `NEVR-BUILD`: nEVR's installer takes any
    DLL holding that for the runtime itself. `Init` logs the literal; keep a use of it, or the linker's
    `--gc-sections` drops it. `check_mod.py` refuses a DLL with none, two, or the wrong version.

## Commits and PR titles

Commits and PR titles follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/):
`<type>[(scope)][!]: <description>`. Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`,
`test`, `build`, `ci`, `chore`, `revert`. A breaking change (for players or for other mods) is marked
with `!` before the colon or a `BREAKING CHANGE:` footer. The commit message says what changed and why.
`pr-title-check.yml` (`tools/check_pr_title.py`) fails a PR with any other title.

Versions are [SemVer](https://semver.org/) and tags are `v<version>` (see Releasing). There is no
changelog file: the git log is the changelog.

## Credit

Credit the people whose work you build on, every time:

- A commit that draws on a person's code, patch, research or findings carries a `Co-Authored-By`
  trailer for them: `Co-Authored-By: Name <id+login@users.noreply.github.com>` (`gh api users/<login>`
  gives the id). Someone with no GitHub account is credited by name in the commit body. A squash merge
  keeps the trailers, so keep them in the PR body too.
- Say who they are in the README, and in `NOTICE` when you carry their code. Keep the licence of
  anything you copy: `LICENSE` stays plain text of one licence (GitHub must recognise it, and the echo-mods review checks), and any
  further notice goes in `NOTICE`.

## Platforms

Mods are for Echo VR on PC (Windows, and Linux through Proton). The template has no Quest build, so
Quest parity is **not applicable**: say so in the PR body when you change what players see ("Quest: not
applicable, PC-only template"). If your mod gains a Quest twin, a change to player-facing behaviour
says in its PR body what the other platform's status is: done in this PR, already present
(`file:line`), not applicable (why), or a linked issue for the twin.

## Taking someone else's patch

Nothing from another project's patch, hook or address list is taken verbatim. Before you build an
equivalent, reconstruct and analyse the patched code: every function the patch touches, its callers,
and what each byte change does. Write down what you found (in the PR body or a doc in the repo), then
design your own implementation from that understanding, to this template's standard: checked bytes
(rule 3), a log line, a test, a stated expectation. Their address list says where to look; it is not
the design. If the same site is already hooked by nEVR, use what nEVR offers (rule 4).

## Prefer a hook to a byte patch

Replace or wrap a function with a hook (`hooks::Hook`, `-DECHO_MOD_MINHOOK=ON`) whose code says, in
readable C++, what the original did and what you change. A byte patch or NOP is the exception, for
where a hook would cost something measurable (a per-frame hot path, a call too frequent to detour).
The PR names the case and the reason, and a number where it can. Either way the bytes are checked
first (rule 3).

## Options and settings

The launcher passes `args` from `config.yaml` to `NvrPluginInitEx`: a flat object, all values
strings, nested keys as `a.b`, lists joined with commas. Read them with `mod::Arg`,
`mod::ArgBool`, `mod::ArgNumber`. The launcher refuses `${...}` in values.

`<Stem>.plugin.json` describes the settings the launcher draws (switches, sliders, choices). Its
format is the launcher's
[docs/plugins/settings.md](https://github.com/marshmallow-mia/EchoVR_Launcher/blob/main/docs/plugins/settings.md)
(schema: `docs/plugins/plugin.schema.json`). With `"store": {"kind": "args"}` the values arrive as
args. The release puts its `settings` object into the published `echo-mod.json`.

## nEVR's runtime exports

`mod::RuntimeExport(name)` finds an nEVR export in `nevr.dll`, then `BugSplat64.dll`, then
`dbgcore.dll` (nEVR is moving its runtime into `nevr.dll`). Null when there is none: handle that.

| Export | Signature |
|---|---|
| `NEVR_RegisterResourceOverride` | `void (uint64_t type_hash, uint64_t name_hash, const void* data, uint64_t size, const char* label)` |
| `NEVR_DeregisterResourceOverrides` | `void (const void* start, const void* end)` |
| `NEVR_ResetResourceOverrides` | `void (void)` |

Resource overrides replace a game resource as it is read. `data` must stay valid while the
override is registered.

## Plugin assets (API v7)

A plugin can carry a level or resource inside its own DLL and register it with nEVR: no extraction, no
copy. The template has the wrappers and one example:

- `include/plugin_assets.h`: `nevr::RegisterAsset(type_hash, name_hash, data, size, label)` returns an
  `NevrAssetStatus` (or `NEVR_ASSET_UNAVAILABLE`, -1, on a host with no asset exports) and
  `nevr::DeregisterAssets(start, end)`.
- `examples/assets/asset_example.cpp`: registers one asset from `mod::Start` (so from `NvrPluginInit`/`InitEx`),
  checks the status, and deregisters from `mod::Stop` (which `NvrPluginShutdown` calls). It is compiled only with
  `cmake -DECHO_MOD_ASSET_EXAMPLE=ON`, and CMake refuses that unless `echo-mod.json` says `"api": 7`. The
  placeholder hashes and bytes in it must be replaced; a mod that ships assets says so in its `summary`.

Rules that come with it:

- **Assets are not a capability.** nevr-runtime's `NvrPluginCapabilities` has no asset bit
  (`src/extension/plugin_interface.h:249-261`; `HOOKS_ENGINE` is the last, at :259). Don't add one to
  `echo-mod.json`. A plugin that carries assets sets `"api": 7` and declares what it does.
- Keep `data` in the DLL's image (a `const` array or a resource section), never on the heap. It must stay valid
  until the asset is deregistered.
- Register in init, before the engine loads the name. A refused registration (`NEVR_ASSET_ALREADY_LOADED`,
  `DUPLICATE`, `BAD_ARGUMENT`) is a log warning on the host side too: check the status and log it.
- The contract (exports, status values, lifetime, what is served, what the login reports) is in nevr-runtime
  [docs/reference/plugin-assets.md](https://github.com/EchoTools/nevr-runtime/blob/main/docs/reference/plugin-assets.md).
  Read it there, not from a copy.

## Content packs (`kind: "pack"`)

**Not published yet:** `check_mod.py` refuses `kind: "pack"` ("content packs come later"), so
a pack can't be submitted or released to players for now. Build a plain `mod` (one DLL).
What follows is how packs will work.

A pack is the DLL plus game content that NvrContentOverlay serves:

```
content/<content id>/content.json      (and what it lists)
echo-mod.json: "kind": "pack", "pack": { "content": "<content id>" }
```

The release zips `plugins/<file>`, `plugins/<Stem>.plugin.json` and `content/<content id>/`. The
launcher installs NvrContentOverlay itself, and packs need an nEVR with the early load pass
(launcher Beta). The `content.json` format is in the launcher's
[docs/launcher/mods.md](https://github.com/marshmallow-mia/EchoVR_Launcher/blob/main/docs/launcher/mods.md#content-packs).

## Releasing

1. Bump `version` in `echo-mod.json` (semver: a breaking change for players or other mods bumps
   MAJOR, a feature MINOR, a fix PATCH; a test build gets a prerelease part: `1.3.0-beta.1`).
2. Commit, tag `v<version>` on that commit, push the tag. Nothing else.
3. `release.yml` builds (the tag's commit goes into the DLL's identity, rule 14), smoke-tests, checks
   the tag against the manifest, packs `dist/`, checks `dist/` with this repo's own
   `tools/check_mod.py --published`, attests the files and opens a **draft** GitHub release (a
   prerelease when the version has a prerelease part). The draft has exactly three files:
   - `<id>-v<version>-windows.zip`: the DLL, `LICENSE`, `NOTICE` (when the repo has one), the
     `<Stem>.plugin.json` settings sheet (when the mod has settings) and a `SHA256SUMS` over those.
     Flat, fixed dates, so the same files make the same zip.
   - `echo-mod.json`: the manifest with `version`, `prerelease`, `settings`, `package` and `source`
     filled in. It has no `sha256` or `size`: signing changes the DLL's bytes.
   - `SHA256SUMS`: the zip and `echo-mod.json`.
4. A draft is not live. For a mod EchoTools releases, the project's release signer takes the
   attested files, signs the DLL inside the zip, replaces the zip and its sums in the draft and
   publishes it; the signer's plugin-release spec lists what it checks. Nobody uploads or edits files
   by hand, the author included. Once the release is published the catalogue picks it up (about 5
   minutes) and the result ("live", or why not) is a comment on the mod's submission issue.

Published versions are immutable: never move or reuse a tag, never replace release files. A
broken release is fixed by a new version. A published version that must not be used any more
is pulled by the maintainers (ask on the submission issue, or the **Pull a version** form in
echo-mods): launchers go back to the version before.

Check a release locally like CI does: `python3 tools/package.py --dll build/mingw/<file>`, then
`python3 tools/check_mod.py --published dist --tag v<version>`. `python3 tests/test_check_mod.py`
tests the checks themselves.

## Distribution, briefly

- A mod reaches the launcher after its first submission at
  [EchoTools/echo-mods](https://github.com/EchoTools/echo-mods/issues/new/choose) is approved.
  From then on every release of it is picked up automatically, if its checks and attestation hold.
- Prereleases are offered only to players who turn on prereleases for that mod.
- After the first approval the author has a dev channel (SFTP with the GitHub account's SSH keys,
  the code in `DEV-CODE.txt`) for test builds. In the launcher the code opens it for the author's
  EchoVRCE account and the accounts in `access.json` in that folder:
  `{"schema": 1, "accounts": ["<EchoVRCE account ID>", ...]}` (at most 50; account IDs only,
  copied on the launcher's EchoVRCE page; usernames are refused). The same list opens the
  author's `private` mods. `ACCESS-STATUS.txt` there says what was found.

## Before you push

Run `just verify`. Put the commands you ran and what they printed in the PR body; don't write "tested"
without the output.

## Before you say it's done

- [ ] `echo-mod.json` has the real `id`, `name`, `summary`, `author`, `file`, `license`, and a semver `version`
- [ ] `just verify` passes
- [ ] the PR title is a Conventional Commits header, and anyone whose work you used has a `Co-Authored-By`
- [ ] `<Stem>.plugin.json` renamed to match `file`, `settings` points at it (or both removed)
- [ ] capabilities match the code
- [ ] `tools/ci-build.sh` (or the build workflow) passes with no errors
- [ ] tried in the game: the launcher shows the mod as **Loaded**, and its log shows `Start` ran
