"""Create a portable source delivery from an explicit product-only allowlist."""
import ast
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from src.workbench.store import ROOT


CORE_MODULES = ["__init__.py", "config.py", "errors.py", "schemas.py", "llm_client.py", "prompts.py",
                "storage.py", "retrieval.py", "utils.py", "knowledge_delivery.py", "knowledge_library.py",
                "modeling_records.py", "skill_loader.py", "solver_runtime.py"]
PRODUCT_MODULES = ["__init__.py", "adapter.py", "app.py", "cases.py", "cli.py", "jobs.py", "model.py",
                   "package.py", "service.py", "solver.py", "store.py", "explanations.py", "usability.py", "study_ui.py", "hosting.py", "hosting_ui.py", "share.py", "manual_study.py", "manual_ui.py", "guidance.py", "charts.py", "review.py", "review_ui.py", "flow.py", "theme.py", "workspace_ui.py", "public_demo.py"]
DOCUMENTS = ["README.md", "AGENTS.md", "OptiFlow-PRD.md", "OptiFlow-Agent-Spec.md", "DEMO-GUIDE.md",
             "DEPLOY-GUIDE.md", "docs/VALIDATION.md", "docs/CLEANUP-PLAN.md", "docs/CLEANUP-MANIFEST.json", "docs/P0-DELIVERY.md",
             "docs/USABILITY-GUIDE.md", "docs/P0-ACCEPTANCE.json", "docs/ONLINE-STUDY.md", "docs/WINDOWS-SHARE.md", "docs/MANUAL-STUDY.md", "docs/UX-REDESIGN.md", "docs/RESUME-DEPLOY.md",
             "docs/README.md", "docs/PRODUCT-DECISIONS.md", "docs/ARCHITECTURE.md"]


def product_files(root=ROOT):
    paths = [*DOCUMENTS, "run_experiment.py", "resume_demo.py", "requirements.txt", "requirements-workbench.txt", "Dockerfile", ".dockerignore",
             "compose.yaml", "compose.public.yaml", "deploy/Caddyfile", "deploy.env.example",
             "启动工作台.cmd", "启动外网测试.cmd", "查看外网入口.cmd", "停止外网测试.cmd", "start-local.bat", ".env.example", ".gitignore", ".gitattributes", ".streamlit/config.toml", ".github/workflows/check.yml", "tests/__init__.py",
             "skill_library/knowledge.json", *[f"src/{n}" for n in CORE_MODULES],
             *[f"src/workbench/{n}" for n in PRODUCT_MODULES]]
    paths.extend(p.relative_to(root).as_posix() for p in (root / "src/agents").glob("*.py"))
    paths.extend(p.relative_to(root).as_posix() for p in (root / "tests").glob("test_*.py"))
    paths.extend(p.relative_to(root).as_posix() for p in (root / "docs/assets").glob("*.png"))
    return sorted(set(paths))


def sanitized_config(source):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HARDCODED_API_KEY" for t in node.targets):
            node.value = ast.Constant("")
    return ast.unparse(tree) + "\n"


def build_package(destination, *, profile="platform"):
    if profile not in {"platform", "resume"}:
        raise ValueError("未知交付包类型。")
    destination = Path(destination).resolve()
    if not destination.is_relative_to(ROOT):
        raise ValueError("交付包请生成在当前项目目录内。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for relative in product_files():
            path = ROOT / relative
            if not path.is_file():
                raise ValueError("交付文件缺失：" + relative)
            content = path.read_bytes()
            if relative == "src/config.py":
                content = sanitized_config(content.decode("utf-8-sig")).encode("utf-8")
            if profile == "resume" and relative == ".streamlit/config.toml":
                content = content.replace(b'address = "127.0.0.1"', b'address = "0.0.0.0"')
            if profile == "resume" and relative in {"requirements.txt", "requirements-workbench.txt"}:
                content = ("streamlit==1.65.0\ncvxpy==1.7.5\nscipy==1.15.3\nopenai==1.60.1\npydantic==2.10.6\npandas==2.2.3\n").encode()
            prefix = "" if profile == "resume" else "OptiFlow/"
            archive.writestr(prefix + relative, content)
            manifest.append({"path": relative, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        archive.writestr(("" if profile == "resume" else "OptiFlow/") + "PACKAGE-MANIFEST.json", json.dumps({
            "product": "OptiFlow", "version": "2.0", "files": manifest,
            "profile": profile,
            "excludes": "credentials, task data, experiments, datasets, old results, environments and model caches",
        }, ensure_ascii=False, indent=2))
    return {"package": str(destination), "file_count": len(manifest), "bytes": destination.stat().st_size}
