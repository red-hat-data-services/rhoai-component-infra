#!/usr/bin/env python3
"""
Script to update VLLM versions in individual repository Dockerfiles
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

# Repository and file mappings
REPO_MAPPINGS = {
    'vllm': {
        'repo': 'red-hat-data-services/vllm',
        'files': ['Dockerfile.ubi']
    },
    'vllm-rocm': {
        'repo': 'red-hat-data-services/vllm-rocm', 
        'files': ['Dockerfile.rom.ubi']
    },
    'vllm-cpu': {
        'repo': 'red-hat-data-services/vllm-cpu',
        'files': ['Dockerfile.ppc64le.ubi', 'Dockerfile.s390x.ubi']
    },
    'vllm-gaudi': {
        'repo': 'red-hat-data-services/vllm-gaudi',
        'files': ['Dockerfile.hpu.ubi']
    }
}

class VLLMRepositoryUpdater:
    def __init__(self):
        self.github_token = os.environ.get('GITHUB_TOKEN')
        self.target_branch = os.environ.get('TARGET_BRANCH', 'main')
        self.runtime_filter = os.environ.get('RUNTIME_FILTER', 'all')
        self.dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
        self.work_dir = None
        self.summary_lines = []
        self.pr_count = 0
        
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
    
    def update_dockerfile_version(self, dockerfile_path, new_version):
        """Update the VLLM_VERSION ARG in a Dockerfile"""
        if not dockerfile_path.exists():
            print(f"Warning: {dockerfile_path} not found, skipping...")
            return False
            
        with open(dockerfile_path, 'r') as f:
            content = f.read()
        
        # Pattern to match ARG VLLM_VERSION=... with optional quotes
        # This pattern preserves quotes if they exist, or adds them if they don't
        pattern = r'^(\s*ARG\s+VLLM_VERSION\s*=\s*)(["\']?)([^"\'\r\n]+)(\2)(\s*)$'
        
        def replacement(match):
            prefix = match.group(1)  # "ARG VLLM_VERSION="
            quote_start = match.group(2)  # Opening quote (if any)
            quote_end = match.group(4)  # Closing quote (should match opening)
            trailing = match.group(5)  # Trailing whitespace
            
            # Always use double quotes for consistency
            return f'{prefix}"{new_version}"{trailing}'
        
        updated_content = re.sub(
            pattern,
            replacement,
            content,
            flags=re.MULTILINE
        )
        
        if content == updated_content:
            print(f"No changes needed in {dockerfile_path}")
            return False
        
        if self.dry_run:
            print(f"DRY RUN: Would update {dockerfile_path} VLLM_VERSION to \"{new_version}\"")
            return True
        
        with open(dockerfile_path, 'w') as f:
            f.write(updated_content)
        
        print(f"Updated {dockerfile_path} VLLM_VERSION to \"{new_version}\"")
        return True
    
    def create_pr(self, repo_dir, repo_name, runtime, version, files_updated):
        """Create a pull request with the changes"""
        if self.dry_run:
            print(f"DRY RUN: Would create PR for {repo_name}")
            return "dry-run-pr-url"
            
        branch_name = f"update-vllm-version-{version.replace('.', '-')}"
        
        # Check if there are any changes
        stdout, _ = self.run_command("git status --porcelain", cwd=repo_dir, check=False)
        if not stdout.strip():
            print(f"No changes to commit in {repo_name}")
            return None
        
        # Create and switch to new branch
        self.run_command(f"git checkout -b {branch_name}", cwd=repo_dir)
        
        # Add and commit changes
        self.run_command("git add .", cwd=repo_dir)
        
        commit_message = f"Update VLLM_VERSION to {version} for {runtime}\n\nFiles updated:\n" + \
                        "\n".join(f"- {f}" for f in files_updated)
        
        self.run_command(f'git commit -m "{commit_message}"', cwd=repo_dir)
        
        # Push the branch
        remote_url = f"https://x-access-token:{self.github_token}@github.com/{repo_name}.git"
        self.run_command(f"git remote set-url origin {remote_url}", cwd=repo_dir)
        self.run_command(f"git push origin {branch_name}", cwd=repo_dir)
        
        # Create PR using GitHub API
        pr_data = {
            "title": f"Update VLLM_VERSION to {version} for {runtime}",
            "body": f"""This PR updates the VLLM_VERSION to `{version}` for the `{runtime}` runtime.

**Files updated:**
{chr(10).join(f'- `{f}`' for f in files_updated)}

**Runtime:** {runtime}
**Version:** {version}
**Target Branch:** {self.target_branch}

This PR was automatically generated by the update-vllm-repositories GitHub Action.""",
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
    
    def process_runtime(self, runtime, version):
        """Process updates for a single runtime"""
        if runtime not in REPO_MAPPINGS:
            print(f"Warning: No repository mapping found for runtime '{runtime}'")
            return f"❌ {runtime}: No repository mapping found"
        
        repo_info = REPO_MAPPINGS[runtime]
        repo_name = repo_info['repo']
        files_to_update = repo_info['files']
        
        print(f"\n{'='*60}")
        print(f"Processing {runtime} -> {version}")
        print(f"Repository: {repo_name}")
        print(f"Files: {', '.join(files_to_update)}")
        print(f"{'='*60}")
        
        # Clone repository
        try:
            repo_dir = self.clone_repository(repo_name, self.target_branch)
        except Exception as e:
            error_msg = f"Failed to clone {repo_name}: {e}"
            print(error_msg)
            return f"❌ {runtime}: {error_msg}"
        
        # Update files
        files_updated = []
        for dockerfile in files_to_update:
            dockerfile_path = repo_dir / dockerfile
            if self.update_dockerfile_version(dockerfile_path, version):
                files_updated.append(dockerfile)
        
        if not files_updated:
            print(f"No files were updated for {runtime}")
            return f"⚠️ {runtime}: No changes needed"
        
        # Create PR
        try:
            pr_url = self.create_pr(repo_dir, repo_name, runtime, version, files_updated)
            if pr_url:
                if self.dry_run:
                    return f"🔍 {runtime}: Would create PR (dry run)"
                else:
                    self.pr_count += 1
                    return f"✅ {runtime}: [PR created]({pr_url})"
            else:
                return f"❌ {runtime}: Failed to create PR"
        except Exception as e:
            error_msg = f"Failed to create PR: {e}"
            print(error_msg)
            return f"❌ {runtime}: {error_msg}"
    
    def write_summary(self):
        """Write summary to file"""
        with open('vllm_update_summary.md', 'w') as f:
            f.write(f"**Target Branch:** {self.target_branch}\n")
            if self.runtime_filter and self.runtime_filter != 'all':
                f.write(f"**Runtime Filter:** {self.runtime_filter}\n")
            f.write(f"**Dry Run:** {'Yes' if self.dry_run else 'No'}\n\n")
            
            for line in self.summary_lines:
                f.write(f"{line}\n")
        
        # Write PR count for workflow output
        with open('pr_count.txt', 'w') as f:
            f.write(str(self.pr_count))
    
    def run(self):
        """Main execution method"""
        print("Starting VLLM repositories update process...")
        
        # Load runtime versions
        try:
            runtime_versions = self.load_runtime_versions()
            print(f"Loaded {len(runtime_versions)} runtime versions:")
            for runtime, version in runtime_versions.items():
                print(f"  {runtime}: {version}")
        except Exception as e:
            print(f"Error loading runtime versions: {e}")
            sys.exit(1)
        
        # Filter to only VLLM runtimes
        vllm_runtime_versions = {runtime: version for runtime, version in runtime_versions.items() 
                                if runtime in REPO_MAPPINGS}
        
        if not vllm_runtime_versions:
            print("No VLLM runtime versions found")
            self.summary_lines.append("⚠️ No VLLM runtime versions found")
            self.write_summary()
            return
        
        # Apply runtime filter if specified
        if self.runtime_filter and self.runtime_filter != 'all':
            if self.runtime_filter in vllm_runtime_versions:
                vllm_runtime_versions = {self.runtime_filter: vllm_runtime_versions[self.runtime_filter]}
                print(f"Filtering to runtime: {self.runtime_filter}")
            else:
                print(f"Error: Runtime filter '{self.runtime_filter}' not found in VLLM runtimes")
                sys.exit(1)
        
        print(f"Processing {len(vllm_runtime_versions)} VLLM runtime(s)")
        
        # Create temporary work directory
        self.work_dir = tempfile.mkdtemp(prefix='vllm_repo_update_')
        print(f"Working directory: {self.work_dir}")
        
        try:
            # Process each VLLM runtime
            for runtime, version in vllm_runtime_versions.items():
                result = self.process_runtime(runtime, version)
                self.summary_lines.append(result)
        
        finally:
            # Cleanup
            if self.work_dir and Path(self.work_dir).exists():
                shutil.rmtree(self.work_dir)
                print(f"Cleaned up work directory: {self.work_dir}")
        
        # Write summary
        self.write_summary()
        
        print("\n" + "="*60)
        print("VLLM repositories update process completed!")
        print(f"PRs created: {self.pr_count}")
        print("="*60)

if __name__ == "__main__":
    updater = VLLMRepositoryUpdater()
    updater.run()
