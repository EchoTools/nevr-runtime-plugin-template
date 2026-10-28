// EXAMPLE, OFF BY DEFAULT. Plugin-carried assets (API v7): one asset registered from mod::Start,
// its status checked, and deregistered from mod::Stop (which NvrPluginShutdown calls).
//
// Built only with   cmake -DECHO_MOD_ASSET_EXAMPLE=ON ...   and only with "api": 7 in echo-mod.json.
// Registering an asset changes what the login reports to the game service (nevr_assets), so a
// mod that ships this must say so in its summary. The contract: nevr-runtime
// docs/reference/plugin-assets.md.
#include <windows.h>

#include <cstdint>

#include "mod.h"
#include "plugin_assets.h"

namespace mod {

namespace {

// Placeholders. Replace both with the engine's 64-bit symbol hashes for the resource you carry:
// the type (e.g. the level-info type) and a name no shipped resource has.
constexpr uint64_t kExampleType = 0x1111111111111111ULL;
constexpr uint64_t kExampleName = 0x2222222222222222ULL;

// The resource's bytes, in the plugin image: a const array, never heap memory. The engine reads them
// through the pointer until the asset is deregistered.
alignas(16) const uint8_t kExampleBytes[] = {'E', 'X', 'A', 'M', 'P', 'L', 'E', 0};

}  // namespace

// Called from Start, so from NvrPluginInit or NvrPluginInitEx. Returns false only when nothing was registered,
// so there is nothing for Shutdown to undo on the failure path.
bool AssetExampleStart() {
    const int status =
        nevr::RegisterAsset(kExampleType, kExampleName, kExampleBytes, sizeof(kExampleBytes), "example-asset");
    switch (status) {
        case NEVR_ASSET_OK:
            Log("asset example: registered (%zu bytes)", sizeof(kExampleBytes));
            return true;
        case nevr::NEVR_ASSET_UNAVAILABLE:
            // The host predates API v7 (no export): this mod's asset cannot be served, so the mod doesn't load.
            Warn("asset example: this nEVR has no plugin assets (needs API v7)");
            return false;
        case NEVR_ASSET_BAD_ARGUMENT:
        case NEVR_ASSET_DUPLICATE:
        case NEVR_ASSET_ALREADY_LOADED:
        default:
            // The host also logs the refusal ([NEVR.ASSET] register refused ...). Log our side too.
            Warn("asset example: register refused with status %d", status);
            return false;
    }
}

// Called from Stop. Deregisters every asset whose data lies in this DLL's image. VirtualQuery finds the image
// the way asset-test does; the range covers the whole DLL, so this is also safe if more assets are added later.
void AssetExampleStop() {
    MEMORY_BASIC_INFORMATION mbi = {};
    if (VirtualQuery(reinterpret_cast<const void*>(&AssetExampleStop), &mbi, sizeof(mbi)) == 0) return;
    const auto* base = static_cast<const uint8_t*>(mbi.AllocationBase);
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    nevr::DeregisterAssets(base, base + nt->OptionalHeader.SizeOfImage);
}

}  // namespace mod
