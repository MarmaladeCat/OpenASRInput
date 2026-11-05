# OpenASRInput development requirements

**English** | [简体中文](AGENTS.zh-CN.md)

Inspect Git status first, then read README.md, docs/development.md, docs/testing.md, and docs/release.md.
Repository/layout changes must not regress functionality or performance. Keep this product independently runnable, testable, buildable, and releasable.
Never import other products' source, share databases, or borrow their Python/Node runtimes. Use public protocols across products.
For behavioral changes, select relevant unit, business, UI, native, and package checks. docs/testing.md governs release acceptance.
Never count skips, failures, or inadequate environments as passes. Simulated upstreams cannot replace real model/device/platform acceptance.
docs/ contains current, manually maintained bilingual documentation: English default filenames and linked *.zh-CN.md counterparts. scripts/build.py uses pinned build environments; candidates go to .cache/build/artifacts/, final output to `release/<VERSION>/` with flat packages/checksums. Never output product dist/.
Test output goes to test-results/; tools, containers, and VM state go to .cache/. Commit neither.
Do not carry old repository Git history, development logs, update status, personal paths, internal hosts, or real keys. The new project records its own normal commits.
Commit and push this product before the workspace updates its submodule reference. Never force-push or rewrite shared new-project commits.
