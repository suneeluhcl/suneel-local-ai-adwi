# 🌙 Deep Scan Report — 2026-06-28 01:56

## SUMMARY
- **Organs scanned:** 12
- **Total gaps found:** 36
- **Total broken connections:** 17
- **Total enhancements identified:** 24
- **Missing nerve wiring:** 24
- **Broken symlinks:** 0
- **Old import paths:** 13
- **Broken nerve paths:** 2

---

## ORGAN-BY-ORGAN FINDINGS

### brain/
nerve.json: ✅ | README.md: ✅ | Files: 62
*The brain organ has some gaps and broken connections, but overall it is functional and can be improved with enhancements and additional wiring to other organs.*

**Gaps (3):**
- [MEDIUM] nerve.json does not declare CLI commands in hands/bin/ → `Add 'cli_commands' entry to nerve.json with a list of available CLI commands`
- [LOW] Some subdirectories in brain/ are missing README.md files → `Add README.md files to all subdirectories in brain/`
- [MEDIUM] No CLI command for building knowledge graph is declared in nerve.json → `Add 'build_graph' CLI command to nerve.json and implement it in hands/bin/`

**Broken Connections (2):**
- prediction_engine import is missing in execution_engine.py in `brain/anticipation/execution_engine.py` → Add 'import prediction_engine' to execution_engine.py or implement a fallback
- WORKSPACE path in bootstrap_patterns.py may not be set in `brain/anticipation/bootstrap_patterns.py` → Ensure WORKSPACE environment variable is set before running bootstrap_patterns.py

**Missing Wiring (2):**
- Connection between brain and nervous organs for nerve propagation (brain → nervous)
- Connection between brain and eyes organs for dashboard updates (brain → eyes)

**Enhancements (2):**
- [HIGH] Implement a more advanced anticipation algorithm using machine learning
- [MEDIUM] Add support for multiple knowledge graph formats

### heart/
nerve.json: ✅ | README.md: ✅ | Files: 89
*The heart organ has some gaps and broken connections that need to be addressed, but overall it is functioning properly.*

**Gaps (4):**
- [MEDIUM] Missing nerve.json entry for model_router → `Add 'model_router' to nerve.json provides or needs section`
- [LOW] Missing CLI command for quota_tracker → `Create a new CLI command in hands/bin/ for quota_tracker`
- [LOW] Missing README.md file for model_router → `Create a new README.md file in heart/model_router/ describing its purpose and usage`
- [HIGH] Broken import in health_checker.py → `Fix the import statement for anthropic and openai libraries`

**Broken Connections (2):**
- Broken path reference in nerve.json in `heart/nerve.json` → Update the path reference to a valid location
- Missing dependency for quota_tracker.py in `heart/model_router/quota_tracker.py` → Add the missing dependency to the requirements file

**Missing Wiring (2):**
- Connection between heart and brain for goal planning (heart → brain)
- Connection between heart and eyes for dashboard updates (heart → eyes)

**Enhancements (2):**
- [HIGH] Implement automated goal prioritization
- [MEDIUM] Add real-time monitoring for model usage

### eyes/
nerve.json: ✅ | README.md: ✅ | Files: 43
*The eyes organ has some gaps and broken connections, but overall it is functional and can be improved with enhancements and additional wiring to other organs.*

**Gaps (3):**
- [MEDIUM] Missing 'provides' and 'needs' entries in nerve.json → `Add 'provides': ['dashboard', 'screenshot_manager'] and 'needs': ['brain/memory', 'heart/orchestration'] to nerve.json`
- [LOW] Missing CLI command for screenshot manager → `Add a new file 'screenshot_manager.sh' in hands/bin/ with the necessary commands to interact with eyes/visual/screenshot_manager.py`
- [LOW] Missing README.md for eyes/visual/ → `Create a new file 'README.md' in eyes/visual/ with documentation about the visual monitor and screenshot manager`

**Broken Connections (1):**
- Importing non-existent module 'asyncio' in health_repair_pipeline.py in `eyes/dashboard/execution/health_repair_pipeline.py` → Replace 'import asyncio' with the correct import statement or remove it if not necessary

**Missing Wiring (2):**
- Connection between eyes and brain for memory updates (eyes → brain)
- Connection between eyes and heart for orchestration updates (eyes → heart)

**Enhancements (2):**
- [HIGH] Implement automated testing for dashboard and screenshot manager
- [MEDIUM] Improve the user interface of the dashboard

### ears/
nerve.json: ✅ | README.md: ✅ | Files: 18
*The ears organ is generally well-structured but lacks CLI commands, has potential broken imports, and could benefit from enhancements to its scoring algorithm and feed sources.*

**Gaps (2):**
- [MEDIUM] No CLI command in hands/bin/ for ears organ → `Create a new file in hands/bin/ that points to ears/monitor/digest/digest_builder.py or other relevant scripts`
- [LOW] Some subdirectories in ears/ are missing README files → `Add README files to these directories to document their purpose and contents`

**Broken Connections (1):**
- Potential broken import in digest_builder.py if ACTIVE_TASKS_PATH or BRAIN_LOGS do not exist in `ears/monitor/digest/digest_builder.py` → Add error handling for file existence checks and consider using relative imports

**Missing Wiring (2):**
- Ears organ should notify brain of new digest items for long-term memory storage (ears → brain)
- Ears organ should receive task updates from heart for relevance scoring (heart → ears)

**Enhancements (2):**
- [HIGH] Improve digest scoring algorithm to better prioritize relevant items
- [MEDIUM] Add support for additional feed sources (e.g., Twitter, Reddit)

### nervous/
nerve.json: ✅ | README.md: ✅ | Files: 55
*The nervous organ has some gaps and broken connections that need to be addressed, but overall it is functioning and can be improved with additional enhancements and wiring to other organs.*

**Gaps (4):**
- [MEDIUM] Missing nerve.json entry for nerve_propagator.py script → `Add 'script': 'nervous/nerve_propagator.py' to nerve.json`
- [LOW] Missing CLI command for nerve_status.py script → `Add a new file to hands/bin/ that runs nervous/nerve_status.py`
- [LOW] Missing README.md for nervous/skills/ directory → `Create a new README.md file in nervous/skills/`
- [CRITICAL] Potential broken import in gateway/api.py if FastAPI or uvicorn is not installed → `Run pip3 install fastapi uvicorn --break-system-packages to ensure dependencies are met`

**Broken Connections (2):**
- Potential broken path in nervous/gateway/api.py if WORKSPACE environment variable is not set in `nervous/gateway/api.py` → Ensure WORKSPACE environment variable is set before running the script
- Missing dependency for requests in nervous/gateway/clients/python_client.py in `nervous/gateway/clients/python_client.py` → Run pip3 install requests to ensure the dependency is met

**Missing Wiring (2):**
- Connection between nervous organ and eyes organ for dashboard updates (nervous → eyes)
- Connection between nervous organ and lab organ for evolution engine integration (nervous → lab)

**Enhancements (2):**
- [HIGH] Implement additional error handling in nervous/gateway/api.py for improved robustness
- [MEDIUM] Develop a more comprehensive testing suite for nervous/mcp/server/ scripts

### skeleton/
nerve.json: ✅ | README.md: ✅ | Files: 12
*The skeleton organ has some gaps in its configuration and potential for enhancements, but overall it is functional with minor issues to address.*

**Gaps (2):**
- [MEDIUM] Missing 'provides' and 'needs' entries in nerve.json → `Add 'provides' and 'needs' sections to nerve.json`
- [MEDIUM] Missing CLI commands in hands/bin/ for skeleton organ → `Create CLI commands in hands/bin/ that interact with skeleton organ`

**Broken Connections (1):**
- Potential broken import in __init__.py files in `skeleton/__init__.py and skeleton/rules/__init__.py` → Verify imports in __init__.py files are correct and functional

**Missing Wiring (2):**
- Connection between skeleton and nervous organs for nerve propagation (skeleton → nervous)
- Connection between skeleton and heart organs for task queue management (skeleton → heart)

**Enhancements (2):**
- [HIGH] Implement automated rule validation and enforcement
- [MEDIUM] Add version control for rules and safety boundaries

### blood/
nerve.json: ✅ | README.md: ✅ | Files: 35
*The blood organ has some gaps and broken connections, but overall it is functioning correctly and providing valuable telemetry data for the workspace.*

**Gaps (3):**
- [HIGH] telemetry.db file is missing → `Create an empty telemetry.db file or run the _get_conn function in telemetry_anomaly.py to initialize it`
- [MEDIUM] nerve.json does not declare any CLI commands → `Add a 'cli' section to nerve.json with the list of available CLI commands`
- [MEDIUM] No CLI command for running telemetry_anomaly.py → `Create a new CLI command in hands/bin/ that runs telemetry_anomaly.py`

**Broken Connections (1):**
- telemetry_anomaly.py and compare_agents.py import schema.sql but it's not clear if the file exists or is up-to-date in `blood/telemetry/telemetry_anomaly.py and blood/telemetry/comparison/compare_agents.py` → Verify that schema.sql exists and is up-to-date, and update the imports accordingly

**Missing Wiring (2):**
- blood organ should be connected to nervous organ for nerve propagation (blood → nervous)
- blood organ should be connected to spine organ for health monitoring (blood → spine)

**Enhancements (2):**
- [HIGH] Implement automated repair report analysis to detect recurring issues
- [MEDIUM] Add more detailed logging for telemetry_anomaly.py and compare_agents.py

### hands/
nerve.json: ✅ | README.md: ✅ | Files: 282
*The hands organ has some gaps in nerve.json entries and CLI commands, but overall it is well-structured with opportunities for enhancements and better connections to other organs.*

**Gaps (3):**
- [MEDIUM] nerve.json does not declare automation scripts as provided services → `add 'provides': ['automation_scripts'] to nerve.json`
- [LOW] no CLI command for running evolution_scorer.py → `add a CLI command to run evolution_scorer.py`
- [LOW] some subdirectories lack README.md files → `add README.md files to subdirectories`

**Broken Connections (2):**
- workspace_ci.py may have incomplete import due to truncation in `hands/automation/ci/workspace_ci.py` → verify and complete imports in workspace_ci.py
- evolution_scorer.py depends on spine/state/WORKSPACE_HEALTH.json, which may not exist in `hands/automation/evolution_scorer.py` → ensure WORKSPACE_HEALTH.json exists and is accessible

**Missing Wiring (2):**
- connect hands organ to spine for health score updates (hands → spine)
- link hands automation scripts to lab experiments (hands → lab)

**Enhancements (2):**
- [HIGH] improve error handling in automation scripts
- [MEDIUM] add logging for key events in automation scripts

### mouth/
nerve.json: ✅ | README.md: ✅ | Files: 47
*The mouth organ has some gaps and broken connections, but overall it is functional and can be improved with enhancements and additional wiring to other organs.*

**Gaps (4):**
- [MEDIUM] Missing 'provides' entry in nerve.json for mouth organ → `Add 'provides': ['comms', 'dispatcher'] to nerve.json`
- [MEDIUM] Missing CLI command for mouth organ in hands/bin/ → `Create a new file in hands/bin/ with a descriptive name (e.g., mouth-cli) that points to the mouth organ`
- [LOW] Missing README.md files in some subdirectories of mouth organ → `Create a new README.md file in the specified directory with a brief description of its purpose`
- [HIGH] Broken import statement in mouth/dispatcher/ws.py → `Fix the import statement to correctly point to the intent_classifier module`

**Broken Connections (2):**
- Broken path reference in mouth/dispatcher/intent_classifier.py to leaderboard.json in `mouth/dispatcher/intent_classifier.py` → Update the path to correctly point to the leaderboard.json file
- Missing dependency in mouth/comms/config/access_policy.json for full_disk_access in `mouth/comms/config/access_policy.json` → Add the necessary dependency or modify the access policy to not require it

**Missing Wiring (2):**
- Missing connection between mouth organ and brain organ for intent classification (mouth → brain)
- Missing connection between mouth organ and hands organ for CLI commands (mouth → hands)

**Enhancements (2):**
- [HIGH] Improve natural language processing in mouth/dispatcher/intent_classifier.py
- [MEDIUM] Add support for additional communication channels in mouth/comms/

### dna/
nerve.json: ✅ | README.md: ✅ | Files: 50
*The dna/ organ has some gaps in its implementation, but overall it is well-structured and functional, with opportunities for enhancements and improved connections to other organs.*

**Gaps (3):**
- [MEDIUM] No main entry point for dna/ organ → `Create a __main__.py file to serve as the main entry point for the dna/ organ`
- [MEDIUM] No CLI command for managing feedback loops → `Create a CLI command to manage feedback loops, e.g., hands/bin/feedback-loop-manager`
- [LOW] No README file for dna/agents/hermes/ → `Create a README file to document the hermes agent`

**Broken Connections (1):**
- Potential broken import in dna/feedback/feedback_ingest.py in `dna/feedback/feedback_ingest.py` → Verify imports and fix any broken ones, e.g., check for missing modules or incorrect paths

**Missing Wiring (2):**
- Connect dna/ organ to lab/ organ for automated experimentation (dna → lab)
- Connect dna/ organ to spine/ organ for health monitoring (dna → spine)

**Enhancements (2):**
- [HIGH] Implement automated testing for feedback loop controller
- [MEDIUM] Add support for multiple feedback formats

### lab/
nerve.json: ✅ | README.md: ✅ | Files: 219
*The lab organ has some gaps and broken connections, but overall it is functioning well and has opportunities for enhancements and improved wiring with other organs.*

**Gaps (2):**
- [MEDIUM] Missing CLI command for hypothesis_generator.py → `Add a new file to hands/bin/ that calls lab/autolab/hypothesis_generator.py`
- [LOW] Missing README.md in lab/autolab/experiments/active directory → `Create a new file lab/autolab/experiments/active/README.md to document active experiments`

**Broken Connections (1):**
- Missing import for urllib.request in deep_scan_engine.py in `lab/autolab/deep_scan_engine.py` → Add import statement for urllib.request

**Missing Wiring (2):**
- Connect lab organ to brain organ for improved memory analysis (lab → brain)
- Connect lab organ to nervous organ for improved MCP resource discovery (lab → nervous)

**Enhancements (2):**
- [HIGH] Improve experiment prioritization using machine learning algorithms
- [MEDIUM] Automate the creation of new experiments based on hypothesis generator output

### spine/
nerve.json: ✅ | README.md: ✅ | Files: 52
*The spine organ has some gaps in CLI commands and README files, but overall it is well-structured with opportunities for enhancements and improved connections to other organs.*

**Gaps (3):**
- [MEDIUM] No CLI command for spine/enhancement_logger.py → `Add a CLI command in hands/bin/ to utilize spine/enhancement_logger.py`
- [MEDIUM] No CLI command for spine/tools/brain_injector.py → `Add a CLI command in hands/bin/ to utilize spine/tools/brain_injector.py`
- [LOW] No README.md for spine/enhancement_logger.py and spine/tools/brain_injector.py → `Add a README.md to describe the functionality of these scripts`

**Broken Connections (1):**
- Potential broken import in spine/tools/brain_injector.py due to missing file paths in `spine/tools/brain_injector.py` → Verify and correct the file paths for imports in spine/tools/brain_injector.py

**Missing Wiring (2):**
- Connection between spine/ and heart/ for task context injection (spine → heart)
- Connection between spine/ and nervous/ for enhancement notifications (spine → nervous)

**Enhancements (2):**
- [MEDIUM] Automate the generation of README.md files for scripts in spine/
- [HIGH] Implement a notification system for when new enhancements are logged by spine/enhancement_logger.py

---

## NERVE SYSTEM ISSUES

- ❌ dna.provides.hermes_memory: `~/.hermes/memory/` missing → Create ~/.hermes/memory/ or update nerve_registry.json
- ❌ dna.provides.hermes_agent: `hermes CLI` missing → Create hermes CLI or update nerve_registry.json

---

## BROKEN SYMLINKS


---

## OLD IMPORT PATHS

- `lab/autolab/deep_scan_engine.py`: `from agent_system` → should be `from brain/heart/blood/spine (check which organ)`
- `lab/autolab/deep_scan_engine.py`: `from orchestrator` → should be `from heart.orchestrator`
- `lab/autolab/deep_scan_engine.py`: `from identity` → should be `from dna.identity`
- `lab/autolab/deep_scan_engine.py`: `from autolab` → should be `from lab.autolab`
- `lab/autolab/deep_scan_engine.py`: `from evolution` → should be `from lab.evolution`
- `lab/autolab/deep_scan_engine.py`: `from dashboard` → should be `from eyes.dashboard`
- `lab/autolab/deep_scan_engine.py`: `from visual` → should be `from eyes.visual`
- `lab/autolab/deep_scan_engine.py`: `from monitor` → should be `from ears.monitor`
- `lab/autolab/deep_scan_engine.py`: `from dispatcher` → should be `from mouth.dispatcher`
- `lab/autolab/deep_scan_engine.py`: `from comms` → should be `from mouth.comms`
- `lab/autolab/deep_scan_engine.py`: `import orchestrator` → should be `import heart.orchestrator`
- `lab/autolab/deep_scan_engine.py`: `import autolab` → should be `import lab.autolab`
- `nervous/mcp/server/main.py`: `from comms` → should be `from mouth.comms`
