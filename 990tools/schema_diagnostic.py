#!/usr/bin/env python3
"""
schema_diagnostic.py - Diagnostic script to compare dataclass models with database schema

This script compares each dataclass model (Charity, Grant, Officer, Contractor,
PoliticalContribution, Address, XmlFile, ZipFile) against their corresponding
database tables to identify missing fields in models and extra fields in database.
"""

import re
import ast
from typing import Dict, List, Set, Tuple
from pathlib import Path


class SchemaDiagnostic:
    """Diagnostic tool for comparing dataclass models with database schema"""

    def __init__(self, schema_file: str = "schema_duckdb.sql", models_dir: str = "models"):
        self.schema_file = Path(schema_file)
        self.models_dir = Path(models_dir)
        self.table_columns: Dict[str, Set[str]] = {}
        self.model_fields: Dict[str, Set[str]] = {}
        self.mismatches: Dict[str, Dict[str, List[str]]] = {}

    def parse_schema(self) -> None:
        """Parse the database schema file to extract table column definitions"""
        with open(self.schema_file, 'r') as f:
            content = f.read()

        # Find all CREATE TABLE statements
        table_pattern = r'CREATE TABLE (\w+)\s*\((.*?)\);'
        tables = re.findall(table_pattern, content, re.DOTALL | re.IGNORECASE)

        for table_name, table_content in tables:
            columns = set()

            # Extract column definitions (lines that start with column name)
            lines = table_content.split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('--') and not line.startswith('FOREIGN KEY') and not line.startswith('UNIQUE'):
                    # Extract column name (first word before space or comma)
                    column_match = re.match(r'^(\w+)', line)
                    if column_match:
                        column_name = column_match.group(1).lower()
                        # Skip special columns like PRIMARY KEY, UNIQUE, etc.
                        if column_name not in ['primary', 'foreign', 'unique', 'check', 'constraint']:
                            columns.add(column_name)

            self.table_columns[table_name] = columns

    def parse_model_file(self, model_file: Path) -> Set[str]:
        """Parse a model file to extract fields from to_dict method"""
        with open(model_file, 'r') as f:
            content = f.read()

        # Parse the AST to find the to_dict method
        tree = ast.parse(content)

        fields = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'to_dict':
                # Find return statement with dictionary
                for child in ast.walk(node):
                    if isinstance(child, ast.Return) and isinstance(child.value, ast.Dict):
                        # Extract keys from the dictionary
                        for key in child.value.keys:
                            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                fields.add(key.value.lower())
                            elif isinstance(key, ast.Str):  # Python < 3.8
                                fields.add(key.s.lower())

        return fields

    def parse_models(self) -> None:
        """Parse all model files to extract field definitions"""
        model_mapping = {
            'charity': 'Charities',
            'grant': 'Grants',
            'officer': 'Officers',
            'contractor': 'Contractors',
            'political_contribution': 'PoliticalContributions',
            'address': 'Addresses',
            'xml_file': 'XmlFiles',
            'zip_file': 'ZipFiles'
        }

        for model_name, table_name in model_mapping.items():
            model_file = self.models_dir / f"{model_name}.py"
            if model_file.exists():
                fields = self.parse_model_file(model_file)
                self.model_fields[table_name] = fields
            else:
                print(f"Warning: Model file {model_file} not found")

    def compare_schemas(self) -> None:
        """Compare model fields with database columns and identify mismatches"""
        for table_name in self.table_columns:
            if table_name in self.model_fields:
                db_columns = self.table_columns[table_name]
                model_fields = self.model_fields[table_name]

                missing_in_model = db_columns - model_fields
                extra_in_model = model_fields - db_columns

                if missing_in_model or extra_in_model:
                    self.mismatches[table_name] = {
                        'missing_in_model': sorted(list(missing_in_model)),
                        'extra_in_model': sorted(list(extra_in_model))
                    }

    def generate_report(self) -> str:
        """Generate a detailed report of all schema mismatches"""
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("SCHEMA DIAGNOSTIC REPORT")
        report_lines.append("=" * 80)
        report_lines.append("")

        if not self.mismatches:
            report_lines.append("✅ No schema mismatches found!")
            report_lines.append("")
            report_lines.append("All dataclass models are properly synchronized with the database schema.")
        else:
            report_lines.append("❌ Schema mismatches detected!")
            report_lines.append("")
            report_lines.append(f"Found mismatches in {len(self.mismatches)} table(s):")
            report_lines.append("")

            for table_name, mismatch_info in self.mismatches.items():
                report_lines.append(f"Table: {table_name}")
                report_lines.append("-" * (len(table_name) + 7))

                if mismatch_info['missing_in_model']:
                    report_lines.append("Fields missing in model (present in database):")
                    for field in mismatch_info['missing_in_model']:
                        report_lines.append(f"  - {field}")
                    report_lines.append("")

                if mismatch_info['extra_in_model']:
                    report_lines.append("Extra fields in model (not in database):")
                    for field in mismatch_info['extra_in_model']:
                        report_lines.append(f"  - {field}")
                    report_lines.append("")

                report_lines.append("")

        # Summary statistics
        total_tables = len(self.table_columns)
        mismatched_tables = len(self.mismatches)
        total_missing = sum(len(m['missing_in_model']) for m in self.mismatches.values())
        total_extra = sum(len(m['extra_in_model']) for m in self.mismatches.values())

        report_lines.append("=" * 80)
        report_lines.append("SUMMARY STATISTICS")
        report_lines.append("=" * 80)
        report_lines.append(f"Total tables analyzed: {total_tables}")
        report_lines.append(f"Tables with mismatches: {mismatched_tables}")
        report_lines.append(f"Fields missing in models: {total_missing}")
        report_lines.append(f"Extra fields in models: {total_extra}")
        report_lines.append("")

        if mismatched_tables > 0:
            report_lines.append("RECOMMENDATIONS:")
            report_lines.append("- Update model to_dict() methods to include missing database fields")
            report_lines.append("- Remove extra fields from models that don't exist in database")
            report_lines.append("- Ensure field names match exactly (case-insensitive comparison used)")
            report_lines.append("- Consider updating database schema if model fields are intentionally added")

        return "\n".join(report_lines)

    def run_diagnostic(self) -> str:
        """Run the complete diagnostic process"""
        print("Parsing database schema...")
        self.parse_schema()

        print("Parsing model files...")
        self.parse_models()

        print("Comparing schemas...")
        self.compare_schemas()

        print("Generating report...")
        report = self.generate_report()

        return report


def main():
    """Main entry point"""
    diagnostic = SchemaDiagnostic()
    report = diagnostic.run_diagnostic()
    print(report)


if __name__ == "__main__":
    main()