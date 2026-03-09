#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
War Machine Repository Audit Script
Comprehensive analysis of code quality, architecture, security, and trading performance.

Usage: python audit_repo.py [--output-dir ./audit_reports]

Requirements:
    pip install radon pylint bandit safety gitpython pandas

Generates:
    - Code complexity analysis (cyclomatic, maintainability index)
    - Security vulnerability scan
    - Dependency audit
    - Architecture visualization
    - Trading system health metrics
    - Documentation coverage
    - Git history analysis
"""

import os
import sys
import json
import subprocess
import ast
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Set
import argparse

# Force UTF-8 encoding for Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("Warning: pandas not installed - some reports will be limited")

# Configuration
REPO_ROOT = Path(__file__).parent.absolute()
OUTPUT_DIR = REPO_ROOT / "audit_reports"
EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "models", "backtest_cache", "audit_reports"}
EXCLUDE_FILES = {"__init__.py"}

class CodeAuditor:
    """Main auditor class orchestrating all analysis tasks."""
    
    def __init__(self, repo_path: Path, output_dir: Path):
        self.repo_path = repo_path
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.python_files: List[Path] = []
        self.total_lines = 0
        self.total_files = 0
        self.issues = []
        
        print("War Machine Repository Audit")
        print(f"Repository: {repo_path}")
        print(f"Output: {output_dir}")
        print("=" * 80)
    
    def _write_report(self, filename: str, content: List[str]):
        """Write report with UTF-8 encoding."""
        try:
            with open(self.output_dir / filename, 'w', encoding='utf-8') as f:
                f.write("\n".join(content))
        except Exception as e:
            print(f"  Error writing {filename}: {e}")
    
    def run_full_audit(self):
        """Execute all audit tasks."""
        print("\nScanning repository structure...")
        self.scan_repository()
        
        print("\nAnalyzing code complexity...")
        self.analyze_complexity()
        
        print("\nSecurity vulnerability scan...")
        self.security_scan()
        
        print("\nDependency audit...")
        self.dependency_audit()
        
        print("\nArchitecture analysis...")
        self.analyze_architecture()
        
        print("\nDocumentation coverage...")
        self.analyze_documentation()
        
        print("\nCode quality metrics...")
        self.code_quality_analysis()
        
        print("\nTrading system health...")
        self.trading_system_audit()
        
        print("\nGit history analysis...")
        self.git_analysis()
        
        print("\nGenerating summary report...")
        self.generate_summary()
        
        print(f"\nAudit complete! Reports saved to: {self.output_dir}")
    
    def scan_repository(self):
        """Scan repository for Python files and basic stats."""
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            
            for file in files:
                if file.endswith('.py') and file not in EXCLUDE_FILES:
                    file_path = Path(root) / file
                    self.python_files.append(file_path)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            lines = len(f.readlines())
                            self.total_lines += lines
                    except Exception as e:
                        print(f"  Warning: Could not read {file_path}: {e}")
        
        self.total_files = len(self.python_files)
        print(f"  Found {self.total_files} Python files ({self.total_lines:,} total lines)")
        
        # Save file list
        report = [
            "War Machine File Inventory",
            "=" * 80,
            ""
        ]
        for file_path in sorted(self.python_files):
            rel_path = file_path.relative_to(self.repo_path)
            report.append(str(rel_path))
        
        self._write_report("file_inventory.txt", report)
    
    def analyze_complexity(self):
        """Analyze code complexity using radon."""
        report = [
            "Code Complexity Analysis",
            "=" * 80,
            ""
        ]
        
        try:
            result = subprocess.run(
                ["radon", "cc", str(self.repo_path), "-a", "-s"],
                capture_output=True,
                text=True,
                timeout=60,
                encoding='utf-8'
            )
            
            if result.returncode == 0:
                report.append("CYCLOMATIC COMPLEXITY (radon cc)")
                report.append("-" * 80)
                report.append(result.stdout)
        except FileNotFoundError:
            report.append("Warning: radon not installed: pip install radon")
        except Exception as e:
            report.append(f"Error running radon: {e}")
        
        report.append("")
        
        try:
            result = subprocess.run(
                ["radon", "mi", str(self.repo_path), "-s"],
                capture_output=True,
                text=True,
                timeout=60,
                encoding='utf-8'
            )
            
            if result.returncode == 0:
                report.append("MAINTAINABILITY INDEX (radon mi)")
                report.append("-" * 80)
                report.append(result.stdout)
        except Exception as e:
            report.append(f"Error running radon mi: {e}")
        
        report.append("")
        report.append("MANUAL COMPLEXITY METRICS")
        report.append("-" * 80)
        
        function_counts = []
        class_counts = []
        
        for file_path in self.python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read(), filename=str(file_path))
                    
                    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
                    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
                    
                    if len(functions) > 50 or len(classes) > 10:
                        rel_path = file_path.relative_to(self.repo_path)
                        report.append(f"  {rel_path}: {len(classes)} classes, {len(functions)} functions")
                        
                        if len(functions) > 50:
                            self.issues.append({
                                'severity': 'LOW',
                                'category': 'Complexity',
                                'file': str(rel_path),
                                'message': f'File has {len(functions)} functions - consider splitting'
                            })
                    
                    function_counts.append(len(functions))
                    class_counts.append(len(classes))
            except (SyntaxError, Exception):
                pass
        
        if function_counts:
            report.append(f"\n  Average functions per file: {sum(function_counts)/len(function_counts):.1f}")
            report.append(f"  Average classes per file: {sum(class_counts)/len(class_counts):.1f}")
        
        self._write_report("complexity_analysis.txt", report)
    
    def security_scan(self):
        """Run security vulnerability scans."""
        report = [
            "Security Vulnerability Scan",
            "=" * 80,
            ""
        ]
        
        try:
            result = subprocess.run(
                ["bandit", "-r", str(self.repo_path), "-f", "txt", "-ll"],
                capture_output=True,
                text=True,
                timeout=120,
                encoding='utf-8'
            )
            
            report.append("BANDIT SECURITY SCAN")
            report.append("-" * 80)
            report.append(result.stdout)
            
            if "No issues identified" not in result.stdout:
                self.issues.append({
                    'severity': 'HIGH',
                    'category': 'Security',
                    'file': 'Multiple',
                    'message': 'Bandit found security issues - review bandit output'
                })
        except FileNotFoundError:
            report.append("Warning: bandit not installed: pip install bandit")
        except Exception as e:
            report.append(f"Error running bandit: {e}")
        
        report.append("")
        report.append("MANUAL SECURITY CHECKS")
        report.append("-" * 80)
        
        security_patterns = {
            'hardcoded_secret': [b'password =', b'api_key =', b'token =', b'secret ='],
            'sql_injection': [b'execute(f"', b'execute("', b'cursor.execute(f'],
            'unsafe_yaml': [b'yaml.load(', b'yaml.unsafe_load'],
            'eval_usage': [b'eval(', b'exec('],
        }
        
        findings = defaultdict(list)
        
        for file_path in self.python_files:
            try:
                with open(file_path, 'rb') as f:
                    content = f.read()
                    
                    for pattern_name, patterns in security_patterns.items():
                        for pattern in patterns:
                            if pattern in content:
                                rel_path = file_path.relative_to(self.repo_path)
                                findings[pattern_name].append(str(rel_path))
            except Exception:
                pass
        
        if findings:
            for pattern, files in findings.items():
                report.append(f"  WARNING: {pattern}: Found in {len(files)} files")
                for file in files[:5]:
                    report.append(f"      - {file}")
                if len(files) > 5:
                    report.append(f"      ... and {len(files)-5} more")
                
                self.issues.append({
                    'severity': 'MEDIUM',
                    'category': 'Security',
                    'file': ', '.join(files[:3]),
                    'message': f'Potential {pattern} pattern detected'
                })
        else:
            report.append("  OK: No obvious security anti-patterns detected")
        
        self._write_report("security_scan.txt", report)
    
    def dependency_audit(self):
        """Audit Python dependencies for vulnerabilities."""
        report = [
            "Dependency Security Audit",
            "=" * 80,
            ""
        ]
        
        requirements_file = self.repo_path / "requirements.txt"
        
        if not requirements_file.exists():
            report.append("Warning: No requirements.txt found")
            self._write_report("dependency_audit.txt", report)
            return
        
        with open(requirements_file, 'r') as f:
            deps = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        
        report.append(f"Found {len(deps)} dependencies\n")
        
        try:
            result = subprocess.run(
                ["safety", "check", "--file", str(requirements_file), "--json"],
                capture_output=True,
                text=True,
                timeout=60,
                encoding='utf-8'
            )
            
            if result.stdout:
                try:
                    safety_data = json.loads(result.stdout)
                    if safety_data:
                        report.append("VULNERABILITIES FOUND")
                        report.append("-" * 80)
                        for vuln in safety_data:
                            report.append(f"  Package: {vuln.get('package', 'unknown')}")
                            report.append(f"  Version: {vuln.get('installed_version', 'unknown')}")
                            report.append(f"  Vulnerability: {vuln.get('vulnerability', 'unknown')}")
                            report.append(f"  Fix: {vuln.get('fixed_version', 'Update to latest')}")
                            report.append("")
                            
                            self.issues.append({
                                'severity': 'HIGH',
                                'category': 'Dependency',
                                'file': 'requirements.txt',
                                'message': f"{vuln.get('package')} has known vulnerability"
                            })
                    else:
                        report.append("OK: No known vulnerabilities in dependencies")
                except json.JSONDecodeError:
                    report.append(result.stdout)
        except FileNotFoundError:
            report.append("Warning: safety not installed: pip install safety")
        except Exception as e:
            report.append(f"Error running safety: {e}")
        
        report.append("")
        report.append("DEPENDENCY LIST")
        report.append("-" * 80)
        for dep in deps:
            report.append(f"  {dep}")
        
        self._write_report("dependency_audit.txt", report)
    
    def analyze_architecture(self):
        """Analyze repository architecture and dependencies."""
        report = [
            "Architecture Analysis",
            "=" * 80,
            ""
        ]
        
        directories = defaultdict(list)
        
        for file_path in self.python_files:
            rel_path = file_path.relative_to(self.repo_path)
            parent = rel_path.parent
            directories[str(parent)].append(rel_path.name)
        
        report.append("DIRECTORY STRUCTURE")
        report.append("-" * 80)
        for dir_name, files in sorted(directories.items()):
            report.append(f"\n{dir_name}/ ({len(files)} files)")
            for file in sorted(files)[:10]:
                report.append(f"  - {file}")
            if len(files) > 10:
                report.append(f"  ... and {len(files)-10} more files")
        
        report.append("\n")
        report.append("IMPORT ANALYSIS")
        report.append("-" * 80)
        
        imports = Counter()
        internal_imports = defaultdict(set)
        
        for file_path in self.python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read(), filename=str(file_path))
                    
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imports[alias.name.split('.')[0]] += 1
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                module = node.module.split('.')[0]
                                imports[module] += 1
                                
                                if module in ['app', 'utils']:
                                    rel_path = file_path.relative_to(self.repo_path)
                                    internal_imports[module].add(str(rel_path))
            except Exception:
                pass
        
        report.append("\nTop External Dependencies:")
        for module, count in imports.most_common(15):
            if module not in ['app', 'utils']:
                report.append(f"  {module}: {count} imports")
        
        report.append("\nInternal Module Usage:")
        for module, files in internal_imports.items():
            report.append(f"  {module}: used by {len(files)} files")
        
        self._write_report("architecture_analysis.txt", report)
    
    def analyze_documentation(self):
        """Analyze documentation coverage."""
        report = [
            "Documentation Coverage Analysis",
            "=" * 80,
            ""
        ]
        
        total_functions = 0
        documented_functions = 0
        total_classes = 0
        documented_classes = 0
        undocumented_files = []
        
        for file_path in self.python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read(), filename=str(file_path))
                    
                    file_functions = 0
                    file_doc_functions = 0
                    
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            total_functions += 1
                            file_functions += 1
                            if ast.get_docstring(node):
                                documented_functions += 1
                                file_doc_functions += 1
                        elif isinstance(node, ast.ClassDef):
                            total_classes += 1
                            if ast.get_docstring(node):
                                documented_classes += 1
                    
                    if file_functions > 0 and file_doc_functions == 0:
                        rel_path = file_path.relative_to(self.repo_path)
                        undocumented_files.append((str(rel_path), file_functions))
            except Exception:
                pass
        
        func_coverage = (documented_functions / total_functions * 100) if total_functions > 0 else 0
        class_coverage = (documented_classes / total_classes * 100) if total_classes > 0 else 0
        
        report.append(f"Functions: {documented_functions}/{total_functions} documented ({func_coverage:.1f}%)")
        report.append(f"Classes: {documented_classes}/{total_classes} documented ({class_coverage:.1f}%)")
        report.append("")
        
        if func_coverage < 50:
            self.issues.append({
                'severity': 'MEDIUM',
                'category': 'Documentation',
                'file': 'Multiple',
                'message': f'Low docstring coverage: {func_coverage:.1f}% of functions documented'
            })
        
        if undocumented_files:
            report.append("FILES WITH NO DOCSTRINGS (Top 10):")
            report.append("-" * 80)
            for file, count in sorted(undocumented_files, key=lambda x: x[1], reverse=True)[:10]:
                report.append(f"  {file}: {count} undocumented functions")
        
        readme_files = ['README.md', 'README.rst', 'README.txt']
        has_readme = any((self.repo_path / f).exists() for f in readme_files)
        
        report.append("")
        report.append("PROJECT DOCUMENTATION:")
        report.append("-" * 80)
        report.append(f"  README: {'OK' if has_readme else 'Missing'}")
        report.append(f"  CONTRIBUTING: {'OK' if (self.repo_path / 'CONTRIBUTING.md').exists() else 'Missing'}")
        report.append(f"  LICENSE: {'OK' if (self.repo_path / 'LICENSE').exists() else 'Missing'}")
        
        self._write_report("documentation_coverage.txt", report)
    
    def code_quality_analysis(self):
        """Run pylint for code quality metrics."""
        report = [
            "Code Quality Analysis (Pylint)",
            "=" * 80,
            ""
        ]
        
        try:
            result = subprocess.run(
                ["pylint", str(self.repo_path), "--output-format=text", "--disable=all", 
                 "--enable=missing-docstring,unused-import,unused-variable,undefined-variable"],
                capture_output=True,
                text=True,
                timeout=300,
                encoding='utf-8'
            )
            
            report.append(result.stdout)
            
            if "unused-import" in result.stdout:
                self.issues.append({
                    'severity': 'LOW',
                    'category': 'Code Quality',
                    'file': 'Multiple',
                    'message': 'Unused imports detected - run pylint for details'
                })
        except FileNotFoundError:
            report.append("Warning: pylint not installed: pip install pylint")
        except subprocess.TimeoutExpired:
            report.append("Warning: pylint timed out - repo too large")
        except Exception as e:
            report.append(f"Error running pylint: {e}")
        
        self._write_report("code_quality.txt", report)
    
    def trading_system_audit(self):
        """Trading system specific health checks."""
        report = [
            "Trading System Health Audit",
            "=" * 80,
            ""
        ]
        
        critical_files = {
            'scanner': 'app/core/scanner.py',
            'data_manager': 'app/data/data_manager.py',
            'signal_generator': 'app/core/signal_generator_cooldown.py',
            'discord_alerts': 'app/discord_helpers.py',
            'database': 'app/data/db_connection.py',
            'risk_manager': 'app/risk/risk_manager.py',
        }
        
        report.append("CRITICAL FILE STATUS:")
        report.append("-" * 80)
        for name, path in critical_files.items():
            exists = (self.repo_path / path).exists()
            report.append(f"  {name}: {'OK' if exists else 'MISSING'}")
            if not exists:
                self.issues.append({
                    'severity': 'CRITICAL',
                    'category': 'Trading System',
                    'file': path,
                    'message': f'Critical file missing: {name}'
                })
        
        model_path = self.repo_path / 'models' / 'signal_predictor.pkl'
        report.append(f"  ML Model: {'OK' if model_path.exists() else 'Not found'}")
        
        report.append("")
        report.append("CONFIGURATION FILES:")
        report.append("-" * 80)
        config_files = ['config.py', '.env', 'requirements.txt']
        for config in config_files:
            exists = (self.repo_path / config).exists() or (self.repo_path / 'utils' / config).exists()
            report.append(f"  {config}: {'OK' if exists else 'Not found'}")
        
        migration_dir = self.repo_path / 'migrations'
        if migration_dir.exists():
            migrations = list(migration_dir.glob('*.sql'))
            report.append(f"\n  Database migrations: {len(migrations)} files")
        
        self._write_report("trading_system_audit.txt", report)
    
    def git_analysis(self):
        """Analyze git history for insights."""
        report = [
            "Git History Analysis",
            "=" * 80,
            ""
        ]
        
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-20"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8'
            )
            
            if result.returncode == 0:
                report.append("RECENT COMMITS (Last 20):")
                report.append("-" * 80)
                report.append(result.stdout)
            
            result = subprocess.run(
                ["git", "shortlog", "-sn", "--all"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8'
            )
            
            if result.returncode == 0:
                report.append("")
                report.append("CONTRIBUTORS:")
                report.append("-" * 80)
                report.append(result.stdout)
            
            result = subprocess.run(
                ["git", "branch", "-a"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8'
            )
            
            if result.returncode == 0:
                report.append("")
                report.append("BRANCHES:")
                report.append("-" * 80)
                report.append(result.stdout)
                
        except Exception as e:
            report.append(f"Warning: Git analysis failed: {e}")
        
        self._write_report("git_analysis.txt", report)
    
    def generate_summary(self):
        """Generate executive summary report."""
        report = [
            "=" * 80,
            "WAR MACHINE REPOSITORY AUDIT - EXECUTIVE SUMMARY",
            "=" * 80,
            f"Audit Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Repository: {self.repo_path}",
            "",
            "REPOSITORY STATISTICS:",
            "-" * 80,
            f"  Total Python files: {self.total_files}",
            f"  Total lines of code: {self.total_lines:,}",
            f"  Average LOC per file: {self.total_lines//self.total_files if self.total_files > 0 else 0}",
            ""
        ]
        
        issues_by_severity = defaultdict(list)
        for issue in self.issues:
            issues_by_severity[issue['severity']].append(issue)
        
        report.append("ISSUES SUMMARY:")
        report.append("-" * 80)
        total_issues = len(self.issues)
        report.append(f"  Total issues found: {total_issues}")
        
        for severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            count = len(issues_by_severity[severity])
            if count > 0:
                report.append(f"  {severity}: {count}")
        
        report.append("")
        
        if self.issues:
            report.append("TOP PRIORITY ISSUES:")
            report.append("-" * 80)
            
            priority_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
            sorted_issues = sorted(self.issues, key=lambda x: priority_order.get(x['severity'], 99))
            
            for i, issue in enumerate(sorted_issues[:10], 1):
                report.append(f"{i}. [{issue['severity']}] {issue['category']}")
                report.append(f"   File: {issue['file']}")
                report.append(f"   Issue: {issue['message']}")
                report.append("")
        else:
            report.append("OK: No major issues detected!")
            report.append("")
        
        report.append("GENERATED REPORTS:")
        report.append("-" * 80)
        report_files = list(self.output_dir.glob("*.txt"))
        for report_file in sorted(report_files):
            report.append(f"  - {report_file.name}")
        
        report.extend([
            "",
            "=" * 80,
            "RECOMMENDATIONS:",
            "=" * 80,
            "",
            "1. Review all CRITICAL and HIGH severity issues immediately",
            "2. Update dependencies with known vulnerabilities",
            "3. Improve docstring coverage (target: 75%+)",
            "4. Add unit tests for core trading logic",
            "5. Set up automated CI/CD with code quality checks",
            "6. Document deployment and backup procedures",
            "7. Implement monitoring for production trading system",
            ""
        ])
        
        self._write_report("00_EXECUTIVE_SUMMARY.txt", report)
        
        print("\n" + "\n".join(report))
        
        if PANDAS_AVAILABLE and self.issues:
            try:
                df = pd.DataFrame(self.issues)
                df.to_csv(self.output_dir / "issues.csv", index=False)
                print("\nIssues also saved as CSV: issues.csv")
            except Exception as e:
                print(f"\nWarning: Could not save issues CSV: {e}")


def main():
    parser = argparse.ArgumentParser(description="Audit War Machine repository")
    parser.add_argument("--output-dir", default="./audit_reports", help="Output directory for reports")
    args = parser.parse_args()
    
    repo_root = Path(__file__).parent.absolute()
    output_dir = Path(args.output_dir).absolute()
    
    auditor = CodeAuditor(repo_root, output_dir)
    auditor.run_full_audit()


if __name__ == "__main__":
    main()
