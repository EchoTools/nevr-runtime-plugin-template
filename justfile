# Recipes for building and checking the mod. `just` lists them; CI runs the same commands.
# Needs MinGW-w64, CMake, Ninja, Wine (smoke test), clang-format, shellcheck and Python 3 on Linux.

set shell := ["bash", "-euo", "pipefail", "-c"]

mod_file := `python3 -c 'import json; print(json.load(open("echo-mod.json"))["file"])'`
version := `python3 -c 'import json; print(json.load(open("echo-mod.json"))["version"])'`
sources := "src/*.cpp src/*.h tests/smoke_host.c"

default:
    @just --list

# Configure and build build/mingw/<file>.dll (warnings are errors, as in CI)
build:
    cmake --preset mingw -DECHO_MOD_WERROR=ON
    cmake --build --preset mingw

# Unit tests of the checks (needs the DLL, so it builds first)
test: build
    python3 tests/test_check_pr_title.py
    python3 tests/test_check_mod.py

# The release check: build, Wine smoke test, manifest and DLL checks, then pack a release and check it
check:
    tools/ci-build.sh
    python3 tools/package.py --dll "build/mingw/{{ mod_file }}" --out build/dist
    python3 tools/check_mod.py --published build/dist --tag "v{{ version }}"

# Formatting and static checks, no build needed
lint: fmt-check
    shellcheck tools/*.sh
    python3 -I -m py_compile tools/*.py tests/*.py

# Format the sources in place
fmt:
    clang-format -i {{ sources }}

# Fail if a source file needs formatting
fmt-check:
    clang-format --dry-run --Werror {{ sources }}

# The whole gate CI runs on every push and pull request. Run it before you push.
verify: lint check test

# Remove build output
clean:
    rm -rf build dist
