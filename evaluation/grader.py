"""Automated grading - compares outputs to oracle files."""
import logging
from pathlib import Path
from typing import Dict, Any
from odf.opendocument import load
from odf import table, text

logger = logging.getLogger(__name__)


def read_ods_data(file_path: Path) -> Dict[str, list[list[tuple[str, str]]]]:
    """
    Read all data from an ODS file including formulas.
    
    Args:
        file_path: Path to ODS file
    
    Returns:
        Dict mapping sheet names to 2D arrays of (value, formula) tuples
        formula is empty string if no formula
    """
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
                # Get text content
                paragraphs = cell.getElementsByType(text.P)
                if paragraphs:
                    cell_value = str(paragraphs[0])
                else:
                    cell_value = ""
                
                # Get formula if exists
                formula = cell.getAttribute('formula') or ""
                
                row_data.append((cell_value, formula))
            
            rows.append(row_data)
        
        sheets[sheet_name] = rows
    
    return sheets


def compare_numeric(value1: str, value2: str, tolerance: float = 0.01) -> bool:
    """
    Compare two numeric values with tolerance.
    
    Args:
        value1: First value as string
        value2: Second value as string
        tolerance: Acceptable relative difference (default 0.01 = 1%)
    
    Returns:
        True if values are within tolerance
    """
    try:
        num1 = float(value1)
        num2 = float(value2)
        
        if num2 == 0:
            return abs(num1 - num2) < tolerance
        else:
            return abs((num1 - num2) / num2) < tolerance
            
    except (ValueError, TypeError):
        # Not numeric, do string comparison
        return value1.strip() == value2.strip()


def convert_excel_to_sympy(formula: str, row: int, col: int) -> str:
    """
    Convert Excel-style formula to sympy expression.
    
    Args:
        formula: Excel formula (e.g., "=B2/(1+D2*C2/365)")
        row: Current row index
        col: Current column index
    
    Returns:
        Sympy-compatible expression
    """
    import re
    
    # Remove = prefix
    expr = formula.lstrip('=')
    
    # Replace cell references with variable names
    # B2 -> b2, D2 -> d2, etc.
    expr = re.sub(r'([A-Z]+)(\d+)', lambda m: f'{m.group(1).lower()}{m.group(2)}', expr)
    
    return expr


def formulas_match(formula1: str, formula2: str, row: int = 2, col: int = 4) -> bool:
    """
    Check if two formulas are mathematically equivalent using sympy.
    
    Args:
        formula1: First formula
        formula2: Second formula
        row: Row index (for cell reference context)
        col: Column index
    
    Returns:
        True if formulas are equivalent
    """
    try:
        from sympy import sympify, simplify
        from sympy.parsing.sympy_parser import parse_expr
        
        # Convert both to sympy expressions
        expr1_str = convert_excel_to_sympy(formula1, row, col)
        expr2_str = convert_excel_to_sympy(formula2, row, col)
        
        # Parse with sympy
        expr1 = parse_expr(expr1_str)
        expr2 = parse_expr(expr2_str)
        
        # Simplify and compare
        diff = simplify(expr1 - expr2)
        
        # If difference simplifies to 0, they're equivalent
        return diff == 0
        
    except Exception as e:
        # If sympy parsing fails, fall back to string comparison
        logger.debug(f"Sympy comparison failed: {e}, falling back to string match")
        
        # Normalize and compare strings
        norm1 = formula1.replace(" ", "").replace("=", "").upper()
        norm2 = formula2.replace(" ", "").replace("=", "").upper()
        
        return norm1 == norm2


def grade_task_run(task_id: str, run_dir: Path, tolerance: float = 0.01) -> Dict[str, Any]:
    """
    Grade a task run by comparing outputs to oracle.
    
    Args:
        task_id: Task identifier
        run_dir: Path to run directory (e.g., runs/banking_001/run_001/)
        tolerance: Numeric comparison tolerance
    
    Returns:
        Grading results with score and feedback
    """
    try:
        # Get task definition
        from orchestration.task_manager import TaskManager
        tm = TaskManager()
        task_def = tm.load_task(task_id)
        
        # Get oracle files
        oracle_files = tm.get_oracle_files(task_id)
        expected_outputs = task_def.get("expected_outputs", [])
        
        if not expected_outputs:
            return {
                "passed": True,
                "score": 1.0,
                "feedback": "No expected outputs defined"
            }
        
        # Compare each expected output
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
            
            # Read both files
            try:
                output_data = read_ods_data(output_file)
                oracle_data = read_ods_data(oracle_file)
            except Exception as e:
                errors.append(f"Failed to parse {expected_filename}: {e}")
                continue
            
            # Compare each sheet
            for sheet_name, oracle_rows in oracle_data.items():
                if sheet_name not in output_data:
                    errors.append(f"Sheet '{sheet_name}' missing from output")
                    total_cells += sum(len(row) for row in oracle_rows)
                    continue
                
                output_rows = output_data[sheet_name]
                
                # Compare each cell
                for row_idx, oracle_row in enumerate(oracle_rows):
                    if row_idx >= len(output_rows):
                        errors.append(f"Sheet '{sheet_name}' row {row_idx+1} missing")
                        total_cells += len(oracle_row)
                        continue
                    
                    output_row = output_rows[row_idx]
                    
                    for col_idx, (oracle_value, oracle_formula) in enumerate(oracle_row):
                        # Skip empty oracle cells
                        if not oracle_value.strip() and not oracle_formula.strip():
                            continue
                        
                        total_cells += 1
                        
                        if col_idx >= len(output_row):
                            col_letter = chr(65 + col_idx)
                            errors.append(f"Cell {sheet_name}!{col_letter}{row_idx+1} missing")
                            continue
                        
                        output_value, output_formula = output_row[col_idx]
                        
                        # If output has a formula
                        if output_formula:
                            # If oracle also has formula, compare formulas
                            if oracle_formula:
                                if formulas_match(output_formula, oracle_formula):
                                    correct_cells += 1
                                    logger.debug(f"Formula match: {output_formula}")
                                else:
                                    col_letter = chr(65 + col_idx)
                                    errors.append(
                                        f"{sheet_name}!{col_letter}{row_idx+1}: "
                                        f"formula mismatch: expected '{oracle_formula}', got '{output_formula}'"
                                    )
                            # Oracle expects value but got formula - check if they'd be equivalent
                            # For now, mark as incorrect (too complex to evaluate formulas)
                            else:
                                col_letter = chr(65 + col_idx)
                                errors.append(
                                    f"{sheet_name}!{col_letter}{row_idx+1}: "
                                    f"expected value '{oracle_value}', got formula '{output_formula}'"
                                )
                        # Otherwise compare values with tolerance
                        elif compare_numeric(output_value, oracle_value, tolerance):
                            correct_cells += 1
                        else:
                            col_letter = chr(65 + col_idx)
                            errors.append(
                                f"{sheet_name}!{col_letter}{row_idx+1}: "
                                f"expected '{oracle_value}', got '{output_value}'"
                            )
        
        # Calculate score
        if total_cells == 0:
            score = 0.0
            passed = False
            feedback = "No cells to grade - missing oracle or outputs"
        else:
            score = correct_cells / total_cells
            
            # Check task mode - computer use requires 100%, tool use allows 90%
            task_mode = task_def.get('mode', 'tool_use')
            if task_mode == 'computer_use':
                passed = (score == 1.0)  # Perfect score required for GUI tasks
                threshold_desc = "100% required for computer_use"
            else:
                passed = (score >= 0.9)  # 90% threshold for tool use
                threshold_desc = "90% threshold"
            
            feedback = f"Correct: {correct_cells}/{total_cells} cells ({threshold_desc})"
            
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
