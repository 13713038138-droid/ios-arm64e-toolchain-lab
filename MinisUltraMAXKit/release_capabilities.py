#!/usr/bin/env python3
"""R5.6 upgrade parity gate: preserved R5.5 capabilities plus real ReverseLab.

The source-tree gate checks original pinned Swift integration AFTER all patch
scripts ran. These are necessary, not sufficient, for runtime acceptance.
Never claim login, sharing or models work on device from source markers alone.
"""
import argparse
import json
from pathlib import Path
import sys

RULES={
    "original_login_and_provider_adapter": (
       "src/ios/Providers/OpenAI/OpenAIProvider.swift",
       ("detail.localizedCaseInsensitiveContains",)),
    "gpt61_route":(
       "src/ios/Providers/OpenAI/OpenAIModelsAPI.swift",
       ('gpt-6.1-sol',)),
    "share_extension_saved_record":(
       "src/ios/ShareExtension/ShareViewController.swift",
       ("guard saved else",)),
    "share_extension_shared_container":(
       "src/ios/ShareExtension/ShareViewModel.swift",
       ("return SharedContainerStore.savePendingShare(share)",)),
    "shared_group_id":(
       "src/ios/Shared/SharedContainerStore.swift",
       ("group.com.openminis.devultramax.r55",)),
    "fileprovider_safety":(
       "src/ios/MinisApp.swift",
       ("FileProvider registration skipped",)),
    "isolated_app_group_fallback":(
       "src/ios/Agent/Chat/AIChatViewModel+RequestBudget.swift",
       ("minisIsolatedContainerBase",)),
    "auto_engineer_native_entry":(
       "src/ios/Agent/Chat/AIChatViewModel+SlashCommands.swift",
       ('case "devauto"', "minis-reverse")),
    "native_hook_entry":(
       "src/ios/Agent/Chat/AIChatViewModel+SlashCommands.swift",
       ('case "devhook"',)),
    "native_ability_registration":(
       "src/ios/Agent/Session/SkillStore.swift",
       ("installBundledAutopilotSkill()", "installBundledUltraSkill()")),
    "bounded_source_patch_runner":(
       "src/ios/default_mount/usr/local/lib/minis-dev-ultra/source_patch.py",
       ("approve-source-edit",)),
    "engineering_checkpoint":(
       "src/ios/default_mount/usr/local/lib/minis-dev-ultra/auto_engineer_cycle.py",
       ("safe_checkpoint",)),
    "provider_quota_safe_engineer_recovery":(
       "src/ios/default_mount/usr/local/lib/minis-dev-ultra/engineer_recovery.py",
       ("def classify_http_error(", "def local_resume(", "automatic_model_retry",)),
    "recovery_cli":(
       "src/ios/default_mount/usr/local/bin/minis-resume",
       ("engineer_recovery.py",)),
    "existing_deb_factory":(
       "src/ios/default_mount/usr/local/lib/minis-dev-ultra/deb_factory.py",
       ("def ",)),
    "original_macho_binary_inspector":(
       "src/ios/default_mount/usr/local/bin/minis-bin",
       ("devctl.py",)),
    "new_cross_package_reverse_executor":(
       "src/ios/default_mount/usr/local/lib/minis-dev-ultra/reverse_intake.py",
       ("def search_package(", "def analyze_binary(")),
    "new_swift_metadata_parser":(
       "src/ios/default_mount/usr/local/lib/minis-dev-ultra/reverse_lab.py",
       ("swift_nominal_types", "LC_FUNCTION_STARTS")),
    "reverse_cli":(
       "src/ios/default_mount/usr/local/bin/minis-reverse",
       ("reverse_intake.py",)),
    "reverse_hook_bridge_generator":(
       "src/ios/default_mount/usr/local/lib/minis-dev-ultra/reverse_hook_bridge.py",
       ("def prepare(", "def scaffold(", "devctl.cmd_hook(")),
    "reverse_hook_bridge_cli":(
       "src/ios/default_mount/usr/local/bin/minis-reverse-hook",
       ("reverse_hook_bridge.py",)),
    "original_task_journal":(
       "src/ios/default_mount/usr/local/lib/minis-dev-ultra/taskctl.py",
       ("checkpoint",)),
}
FULL_RULES={
    "chat_scroll_performance":(
       "src/ios/Agent/MessageList/MessageListLayout.swift",
       ("preparedFramesAreMonotone",)),
    "skill_archive_import":(
       "src/ios/Agent/Session/SkillStore.swift",
       ("decodedTotal",)),
}
def evaluate(root,level="core"):
    root=Path(root).expanduser().resolve()
    if not root.is_dir(): raise ValueError("OpenMinis source root not found")
    rules={**RULES,**(FULL_RULES if level=="full" else {})}
    checks={}
    for name,(relative,needles) in rules.items():
        file=root/relative
        if not file.is_file() or file.is_symlink():
            checks[name]={"ok":False,"reason":"missing or symlink","file":relative}
            continue
        if file.stat().st_size>8*1024*1024:
            checks[name]={"ok":False,"reason":"unexpected file size","file":relative}
            continue
        content=file.read_text(encoding="utf-8",errors="replace")
        absent=[token for token in needles if token not in content]
        checks[name]={"ok":not absent,"file":relative,
                      "reason":"markers not found" if absent else "source present"}
    failed=[name for name,check in checks.items() if not check["ok"]]
    return {"gate":"Minis R5.6 upgrade parity","stage":level,"status":"PASS" if not failed else "NO-GO",
            "checked":len(checks),"failed":failed,"checks":checks,
            "runtime_sharing_verified":False,"device_verified":False,
            "signing_verified":False,"network_login_verified":False,
            "note":"Static source integration is not equivalent to live behavior, iOS signing or model entitlement."}

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--source-tree",required=True)
    parser.add_argument("--level",choices=("core","full"),default="core")
    parser.add_argument("--out")
    args=parser.parse_args(argv)
    try: result=evaluate(args.source_tree,args.level)
    except (OSError,ValueError) as exc:
        print("NO-GO parity gate: "+str(exc),file=sys.stderr)
        return 2
    blob=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    if args.out:
        target=Path(args.out).expanduser()
        if target.exists() or target.is_symlink():
            print("NO-GO: output path must be new",file=sys.stderr)
            return 2
        target.write_text(blob,encoding="utf-8")
    else: print(blob,end="")
    return 0 if result["status"]=="PASS" else 2

if __name__=="__main__":raise SystemExit(main())
