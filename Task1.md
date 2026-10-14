# Task Description

Research the implementation mechanisms of open-source Claude-Code projects. Based on the provided open-source references, implement a simplified **Code Agent**. The underlying LLM must be `deepseek-v4-pro` via the official API (`https://api.deepseek.com`); local weight deployment is not required.

### Reference Repositories
- https://github.com/ultraworkers/clawcode
- https://github.com/Windy3f3f3f3f/howclaudecodeworks
- https://github.com/anthropics/claudecode

---

## Deliverables & Packaging

### Primary Deliverable: Windows Desktop Application
- Produce a double-click runnable `.exe` executable.
- No pre-installed Python runtime is required on target machines.
- The application shall provide a minimal GUI for:
  - DeepSeek API Key configuration
  - Input file selection
  - Task triggering
  - Output directory assignment

### Fallback Requirement
> [!NOTE]
> If you encounter intractable engineering obstacles when building the Windows desktop `.exe`, you may submit a CLI-launched web-based version as an alternative. The backend service is started from the command line, and users interact entirely via the browser. Partial engineering points will be deducted for this fallback solution.

---

## Agent Input & Output Specification

### Input
1. **Architectural Documentation**: `Architecture_Documentation.md`. Preprocessing to structured JSON is recommended as agent input.
2. **Architectural Views**: `Architecture_View.md`, containing structured syntax descriptions for UML diagrams (PlantUML).

### Output (Non-Exhaustive)
- Project directory layout and full source code files
- Dependency manifest (`requirements.txt` / `package.json`)
- Dockerfile (optional)
- Project README
- Test cases
