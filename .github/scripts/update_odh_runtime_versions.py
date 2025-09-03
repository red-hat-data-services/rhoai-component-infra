#!/usr/bin/env python3
"""
Script to update runtime versions in ODH Model Controller YAML templates
"""

import os
import sys
import yaml
import subprocess
import tempfile
import shutil
import re
from pathlib import Path
import requests
import json

# ODH Model Controller mappings - for YAML annotation updates
ODH_MODEL_CONTROLLER_MAPPINGS = {
    'vllm': {
        'repo': 'red-hat-data-services/odh-model-controller',
        'files': ['config/runtimes/vllm-cuda-template.yaml', 'config/runtimes/vllm-multinode-template.yaml']
    },
    'vllm-rocm': {
        'repo': 'red-hat-data-services/odh-model-controller',
        'files': ['config/runtimes/vllm-rocm-template.yaml']
    },
    'vllm-cpu': {
        'repo': 'red-hat-data-services/odh-model-controller',
        'files': ['config/runtimes/vllm-cpu-template.yaml']
    },
    'vllm-gaudi': {
        'repo': 'red-hat-data-services/odh-model-controller',
        'files': ['config/runtimes/vllm-gaudi-template.yaml']
    },
    'ovms': {
        'repo': 'red-hat-data-services/odh-model-controller',
        'files': ['config/runtimes/ovms-kserve-template.yaml', 'config/runtimes/ovms-mm-template.yaml']
    }
}

class ODHRuntimeVersionUpdater:
    def __init__(self):
        self.github_token = os.environ.get('GITHUB_TOKEN')
        self.target_branch = os.environ.get('TARGET_BRANCH', 'main')
        self.runtime_filter = os.environ.get('RUNTIME_FILTER', 'all')
        self.dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
        self.work_dir = None
        self.summary_lines = []
        
        if not self.github_token:
            raise ValueError("GITHUB_TOKEN environment variable is required")
    
    def load_runtime_versions(self):
        """Load runtime versions from the YAML file"""
        config_path = Path('src/config/update-runtime-version.yaml')
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
            
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
            
        return {item['runtime']: item['version'] for item in data['rhoai-runtime-versions']}
    
    def run_command(self, cmd, cwd=None, check=True):
        """Run a shell command and return the result"""
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, cwd=cwd, check=check
            )
            return result.stdout.strip(), result.stderr.strip()
        except subprocess.CalledProcessError as e:
            print(f"Command failed: {cmd}")
            print(f"Error: {e.stderr}")
            raise
    
    def clone_repository(self, repo_name, branch='main'):
        """Clone a repository to the work directory"""
        repo_url = f"https://github.com/{repo_name}.git"
        repo_dir = Path(self.work_dir) / repo_name.split('/')[-1]
        
        print(f"Cloning {repo_name} (branch: {branch})...")
        
        # Clone the repository
        self.run_command(f"git clone {repo_url} {repo_dir}")
        
        # Checkout the target branch
        self.run_command(f"git checkout {branch}", cwd=repo_dir)
        
        return repo_dir
    
    def update_yaml_annotation(self, yaml_path, new_version):
        """Update the opendatahub.io/runtime-version annotation in a YAML file"""
        if not yaml_path.exists():
            print(f"Warning: {yaml_path} not found, skipping...")
            return False
            
        with open(yaml_path, 'r') as f:
            content = f.read()
        
        # Pattern to match opendatahub.io/runtime-version annotation
        # This pattern handles both quoted and unquoted values, and various indentation
        pattern = r'^(\s*opendatahub\.io/runtime-version\s*:\s*)(["\']?)([^"\'\r\n]+)(\2)(\s*)$'
        
        def replacement(match):
            indent = match.group(1)
            quote_start = match.group(2)
            quote_end = match.group(4)
            trailing = match.group(5)
            return f"{indent}{quote_start}{new_version}{quote_end}{trailing}"
        
        updated_content = re.sub(
            pattern,
            replacement,
            content,
            flags=re.MULTILINE
        )
        
        if content == updated_content:
            print(f"No changes needed in {yaml_path}")
            return False
        
        if self.dry_run:
            print(f"DRY RUN: Would update {yaml_path} opendatahub.io/runtime-version to {new_version}")
            return True
        
        with open(yaml_path, 'w') as f:
            f.write(updated_content)
        
        print(f"Updated {yaml_path} opendatahub.io/runtime-version to {new_version}")
        return True
    
    def create_pr(self, repo_dir, repo_name, runtime_updates, files_updated):
        """Create a pull request for ODH Model Controller with all runtime updates"""
        if self.dry_run:
            print(f"DRY RUN: Would create PR for {repo_name}")
            return "dry-run-pr-url"
            
        branch_name = f"update-runtime-versions-{'-'.join(runtime_updates[0].split(' -> ')[1].replace('.', '-').split('-')[:2])}"
        
        # Check if there are any changes
        stdout, _ = self.run_command("git status --porcelain", cwd=repo_dir, check=False)
        if not stdout.strip():
            print(f"No changes to commit in {repo_name}")
            return None
        
        # Create and switch to new branch
        self.run_command(f"git checkout -b {branch_name}", cwd=repo_dir)
        
        # Add and commit changes
        self.run_command("git add .", cwd=repo_dir)
        
        commit_message = f"Update runtime versions in ODH Model Controller\n\nRuntime updates:\n" + \
                        "\n".join(f"- {update}" for update in runtime_updates) + \
                        f"\n\nFiles updated:\n" + \
                        "\n".join(f"- {f}" for f in files_updated)
        
        self.run_command(f'git commit -m "{commit_message}"', cwd=repo_dir)
        
        # Push the branch
        remote_url = f"https://x-access-token:{self.github_token}@github.com/{repo_name}.git"
        self.run_command(f"git remote set-url origin {remote_url}", cwd=repo_dir)
        self.run_command(f"git push origin {branch_name}", cwd=repo_dir)
        
        # Create PR using GitHub API
        pr_data = {
            "title": f"Update runtime versions in ODH Model Controller",
            "body": f"""This PR updates runtime versions in the ODH Model Controller.

**Runtime Updates:**
{chr(10).join(f'- **{update.split(" -> ")[0]}**: `{update.split(" -> ")[1]}`' for update in runtime_updates)}

**Files Updated:**
{chr(10).join(f'- `{f}`' for f in files_updated)}

**Target Branch:** {self.target_branch}

This PR was automatically generated by the update-odh-runtime-versions GitHub Action.""",
            "head": branch_name,
            "base": self.target_branch
        }
        
        api_url = f"https://api.github.com/repos/{repo_name}/pulls"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        response = requests.post(api_url, headers=headers, json=pr_data)
        
        if response.status_code == 201:
            pr_url = response.json()['html_url']
            print(f"Created PR: {pr_url}")
            return pr_url
        else:
            print(f"Failed to create PR: {response.status_code} - {response.text}")
            return None
    
    def process_odh_updates(self, runtime_versions):
        """Process all ODH Model Controller updates"""
        odh_runtimes = {runtime: version for runtime, version in runtime_versions.items() 
                       if runtime in ODH_MODEL_CONTROLLER_MAPPINGS}
        
        if not odh_runtimes:
            return None, "No ODH Model Controller updates needed"
        
        repo_name = "red-hat-data-services/odh-model-controller"
        
        print(f"\n{'='*60}")
        print(f"Processing ODH Model Controller updates")
        print(f"Repository: {repo_name}")
        print(f"Runtimes: {', '.join(f'{r}={v}' for r, v in odh_runtimes.items())}")
        print(f"{'='*60}")
        
        # Clone repository
        try:
            repo_dir = self.clone_repository(repo_name, self.target_branch)
        except Exception as e:
            error_msg = f"Failed to clone {repo_name}: {e}"
            print(error_msg)
            return None, error_msg
        
        # Update all runtime files
        all_files_updated = []
        runtime_updates = []
        
        for runtime, version in odh_runtimes.items():
            files_to_update = ODH_MODEL_CONTROLLER_MAPPINGS[runtime]['files']
            files_updated = []
            
            for file_path in files_to_update:
                full_path = repo_dir / file_path
                if self.update_yaml_annotation(full_path, version):
                    files_updated.append(file_path)
            
            if files_updated:
                all_files_updated.extend(files_updated)
                runtime_updates.append(f"{runtime} -> {version}")
                print(f"Updated {runtime} ({version}) in {len(files_updated)} files")
        
        if not all_files_updated:
            print(f"No files were updated in {repo_name}")
            return None, f"No changes needed in {repo_name}"
        
        # Create PR
        try:
            pr_url = self.create_pr(repo_dir, repo_name, runtime_updates, all_files_updated)
            if pr_url:
                if self.dry_run:
                    return "dry-run", f"Would create PR in {repo_name} (dry run)"
                else:
                    return pr_url, f"PR created in {repo_name}"
            else:
                return None, f"Failed to create PR in {repo_name}"
        except Exception as e:
            error_msg = f"Failed to create PR in {repo_name}: {e}"
            print(error_msg)
            return None, error_msg
    
    def write_summary(self, pr_url, message):
        """Write summary to file"""
        with open('odh_update_summary.md', 'w') as f:
            f.write(f"**Target Branch:** {self.target_branch}\n")
            if self.runtime_filter and self.runtime_filter != 'all':
                f.write(f"**Runtime Filter:** {self.runtime_filter}\n")
            f.write(f"**Dry Run:** {'Yes' if self.dry_run else 'No'}\n\n")
            
            if pr_url:
                if pr_url == "dry-run":
                    f.write(f"🔍 ODH Model Controller: {message}\n")
                else:
                    f.write(f"✅ ODH Model Controller: [PR created]({pr_url})\n")
            else:
                if "No changes needed" in message or "No ODH Model Controller updates needed" in message:
                    f.write(f"⚠️ ODH Model Controller: {message}\n")
                else:
                    f.write(f"❌ ODH Model Controller: {message}\n")
        
        # Write PR URL for workflow output
        if pr_url and pr_url != "dry-run":
            with open('pr_url.txt', 'w') as f:
                f.write(pr_url)
    
    def run(self):
        """Main execution method"""
        print("Starting ODH Model Controller runtime version update process...")
        
        # Load runtime versions
        try:
            runtime_versions = self.load_runtime_versions()
            print(f"Loaded {len(runtime_versions)} runtime versions:")
            for runtime, version in runtime_versions.items():
                print(f"  {runtime}: {version}")
        except Exception as e:
            print(f"Error loading runtime versions: {e}")
            sys.exit(1)
        
        # Filter runtimes if specified
        if self.runtime_filter and self.runtime_filter != 'all':
            if self.runtime_filter in runtime_versions:
                runtime_versions = {self.runtime_filter: runtime_versions[self.runtime_filter]}
                print(f"Filtering to runtime: {self.runtime_filter}")
            else:
                print(f"Error: Runtime filter '{self.runtime_filter}' not found in config")
                sys.exit(1)
        
        # Create temporary work directory
        self.work_dir = tempfile.mkdtemp(prefix='odh_update_')
        print(f"Working directory: {self.work_dir}")
        
        try:
            # Process ODH Model Controller updates
            pr_url, message = self.process_odh_updates(runtime_versions)
            
        finally:
            # Cleanup
            if self.work_dir and Path(self.work_dir).exists():
                shutil.rmtree(self.work_dir)
                print(f"Cleaned up work directory: {self.work_dir}")
        
        # Write summary
        self.write_summary(pr_url, message)
        
        print("\n" + "="*60)
        print("ODH Model Controller update process completed!")
        print("="*60)

if __name__ == "__main__":
    updater = ODHRuntimeVersionUpdater()
    updater.run()
