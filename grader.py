import logging
from pathlib import Path
from typing import Dict, Any
from odf.opendocument import load
from odf import table, text

logger = logging.getLogger(__name__)


def read_ods_data(file_path: Path) -> Dict[str, list[list[tuple[str, str]]]]:
    """read all data from an ods file including formulas"""
    doc = load(str(file_path))
    sheets = {}
    
    tables = doc.spreadsheet.getElementsByType(table.Table)
    for tbl in tables:
        sheet_name = tbl.getAttribute('name')
        rows = []
        
        for row in tbl.getElementsByType(table.TableRow):
            row_data = []
            cells = row.getElementsByType(table.TableCell)
            
            for cell in cells:
                paragraphs = cell.getElementsByType(text.P)
                cell_value = str(paragraphs[0]) if paragraphs else ""
                formula = cell.getAttribute('formula') or ""
                row_data.append((cell_value, formula))
            
            rows.append(row_data)
        
        sheets[sheet_name] = rows
    
    return sheets


def compare_numeric(value1: str, value2: str, tolerance: float = 0.01) -> bool:
    """compare two numeric values with tolerance"""
    try:
        num1 = float(value1)
        num2 = float(value2)
        
        if num2 == 0:
            return abs(num1 - num2) < tolerance
        else:
            return abs((num1 - num2) / num2) < tolerance
            
    except (ValueError, TypeError):
        return value1.strip() == value2.strip()


def formulas_match(formula1: str, formula2: str, row: int = 2, col: int = 4) -> bool:
    """check if two formulas are mathematically equivalent using sympy"""
    try:
        from sympy import simplify
        from sympy.parsing.sympy_parser import parse_expr
        import re
        
        # Remove = prefix and convert cell refs to lowercase
        expr1_str = formula1.lstrip('=')
        expr2_str = formula2.lstrip('=')
        expr1_str = re.sub(r'([A-Z]+)(\d+)', lambda m: f'{m.group(1).lower()}{m.group(2)}', expr1_str)
        expr2_str = re.sub(r'([A-Z]+)(\d+)', lambda m: f'{m.group(1).lower()}{m.group(2)}', expr2_str)
        
        expr1 = parse_expr(expr1_str)
        expr2 = parse_expr(expr2_str)
        
        diff = simplify(expr1 - expr2)
        return diff == 0
        
    except Exception as e:
        logger.debug(f"Sympy comparison failed: {e}, falling back to string match")
        norm1 = formula1.replace(" ", "").replace("=", "").upper()
        norm2 = formula2.replace(" ", "").replace("=", "").upper()
        return norm1 == norm2


def grade_task_run(task_id: str, run_dir: Path, tolerance: float = 0.01) -> Dict[str, Any]:
    try:
        from orchestration.task_manager import TaskManager
        tm = TaskManager()
        task_def = tm.load_task(task_id)
        
        oracle_files = tm.get_oracle_files(task_id)
        expected_outputs = task_def.get("expected_outputs", [])
        
        if not expected_outputs:
            return {"passed": True, "score": 1.0, "feedback": "No expected outputs defined"}
        
        total_cells = 0
        correct_cells = 0
        errors = []
        
        for expected_filename in expected_outputs:
            output_file = run_dir / expected_filename
            oracle_file = oracle_files.get(expected_filename)
            
            if not output_file.exists():
                errors.append(f"Output file missing: {expected_filename}")
                continue
            
            if oracle_file is None or not oracle_file.exists():
                logger.warning(f"Oracle file not found for {expected_filename}")
                continue
            
            try:
                output_data = read_ods_data(output_file)
                oracle_data = read_ods_data(oracle_file)
            except Exception as e:
                errors.append(f"Failed to parse {expected_filename}: {e}")
                continue
            
            for sheet_name, oracle_rows in oracle_data.items():
                if sheet_name not in output_data:
                    errors.append(f"Sheet '{sheet_name}' missing from output")
                    total_cells += sum(len(row) for row in oracle_rows)
                    continue
                
                output_rows = output_data[sheet_name]
                
                for row_idx, oracle_row in enumerate(oracle_rows):
                    if row_idx >= len(output_rows):
                        errors.append(f"Sheet '{sheet_name}' row {row_idx+1} missing")
                        total_cells += len(oracle_row)
                        continue
                    
                    output_row = output_rows[row_idx]
                    
                    for col_idx, (oracle_value, oracle_formula) in enumerate(oracle_row):
                        if not oracle_value.strip() and not oracle_formula.strip():
                            continue
                        
                        total_cells += 1
                        
                        if col_idx >= len(output_row):
                            col_letter = chr(65 + col_idx)
                            errors.append(f"Cell {sheet_name}!{col_letter}{row_idx+1} missing")
                            continue
                        
                        output_value, output_formula = output_row[col_idx]
                        
                        if output_formula:
                            if oracle_formula:
                                if formulas_match(output_formula, oracle_formula):
                                    correct_cells += 1
                                else:
                                    col_letter = chr(65 + col_idx)
                                    errors.append(
                                        f"{sheet_name}!{col_letter}{row_idx+1}: "
                                        f"formula mismatch: expected '{oracle_formula}', got '{output_formula}'"
                                    )
                            else:
                                col_letter = chr(65 + col_idx)
                                errors.append(
                                    f"{sheet_name}!{col_letter}{row_idx+1}: "
                                    f"expected value '{oracle_value}', got formula '{output_formula}'"
                                )
                        elif compare_numeric(output_value, oracle_value, tolerance):
                            correct_cells += 1
                        else:
                            col_letter = chr(65 + col_idx)
                            errors.append(
                                f"{sheet_name}!{col_letter}{row_idx+1}: "
                                f"expected '{oracle_value}', got '{output_value}'"
                            )
        
        if total_cells == 0:
            score = 0.0
            passed = False
            feedback = "No cells to grade - missing oracle or outputs"
        else:
            score = correct_cells / total_cells
            passed = (score == 1.0)
            
            if passed:
                feedback = f"Perfect! All {correct_cells}/{total_cells} cells correct"
            else:
                feedback = f"Failed: {correct_cells}/{total_cells} cells correct (100% required)"
            
            if errors:
                feedback += f". Errors: {'; '.join(errors[:5])}"
                if len(errors) > 5:
                    feedback += f" (and {len(errors)-5} more)"
        
        return {
            "passed": passed,
            "score": round(score, 3),
            "feedback": feedback,
            "details": {
                "total_cells": total_cells,
                "correct_cells": correct_cells,
                "errors": errors
            }
        }
        
    except Exception as e:
        logger.exception("Grading failed")
        return {
            "passed": False,
            "score": 0.0,
            "feedback": f"Grading error: {str(e)}",
            "error": str(e)
        }

