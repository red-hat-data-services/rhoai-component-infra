RHOAI-Component-Infra
====================

Runtime Version Update Automation
----------
* The infra is responsible for automatically updating runtime versions across multiple repositories:
   * **VLLM Repositories** - Updates `ARG VLLM_VERSION="x.y.z"` in Dockerfiles across VLLM runtime repositories
   * **ODH Model Controller** - Updates `opendatahub.io/runtime-version: x.y.z` annotations in YAML templates
   * **Consolidated Approach** - Creates individual PRs for VLLM repos and a single consolidated PR for ODH Model Controller
* Can be executed manually from the [orchestrator workflow](https://github.com/red-hat-data-services/rhods-devops-infra/actions/workflows/update-all-runtime-versions.yml) or individual workflows:
   * [VLLM Repositories](https://github.com/red-hat-data-services/rhods-devops-infra/actions/workflows/update-vllm-repositories.yml) - Updates Dockerfiles only
   * [ODH Model Controller](https://github.com/red-hat-data-services/rhods-devops-infra/actions/workflows/update-odh-runtime-versions.yml) - Updates YAML templates only
* Updates are based on the configuration in [update-runtime-version.yaml](https://github.com/red-hat-data-services/rhods-devops-infra/blob/main/src/config/update-runtime-version.yaml)
* Supports selective updates by runtime type and dry-run mode for preview
* The workflow automatically handles forking, cloning, updating files, and creating pull requests

Update Runtime Versions
-----------------------------
1. Update the [update-runtime-version.yaml](https://github.com/red-hat-data-services/rhods-devops-infra/blob/main/src/config/update-runtime-version.yaml) with new runtime versions and commit the changes
2. Execute the workflow manually:
   1. Go to [the orchestrator workflow](https://github.com/red-hat-data-services/rhods-devops-infra/actions/workflows/update-all-runtime-versions.yml)
   2. Click on 'Run Workflow'
   3. Select branch as 'main'
   4. Configure options:
      * **Target branch**: Branch to create PRs against (default: main)
      * **Runtime filter**: Update all runtimes or filter to specific runtime
      * **Dry run**: Preview changes without creating PRs
      * **Update components**: Choose to update VLLM repos, ODH controller, or both
   5. Hit the 'Run Workflow' button
3. Review and merge the created pull requests in the target repositories

Supported Runtime Repositories
-----------------------------
* **VLLM**: [red-hat-data-services/vllm](https://github.com/red-hat-data-services/vllm) - `Dockerfile.ubi`
* **VLLM-ROCM**: [red-hat-data-services/vllm-rocm](https://github.com/red-hat-data-services/vllm-rocm) - `Dockerfile.rom.ubi`
* **VLLM-CPU**: [red-hat-data-services/vllm-cpu](https://github.com/red-hat-data-services/vllm-cpu) - `Dockerfile.ppc64le.ubi`, `Dockerfile.s390x.ubi`
* **VLLM-Gaudi**: [red-hat-data-services/vllm-gaudi](https://github.com/red-hat-data-services/vllm-gaudi) - `Dockerfile.hpu.ubi`
* **ODH Model Controller**: [red-hat-data-services/odh-model-controller](https://github.com/red-hat-data-services/odh-model-controller) - Multiple YAML template files

