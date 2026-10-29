from src.solver_runtime import parse_solver_record, normalize_status, legacy_backend, finite_number
import re
import subprocess
import sys
from time import perf_counter
from pathlib import Path
from src.schemas import ExecutionResult

class Evaluator:

    def __init__(self, code_timeout: int=30, objective_atol=1e-06, objective_rtol=1e-06):
        self.code_timeout = code_timeout
        (self.objective_atol, self.objective_rtol) = (objective_atol, objective_rtol)
        self.last_execution_seconds: float | None = None

    def assess(self, execution, reference):
        """Compare a saved execution with the reference, without executing again."""
        objective = finite_number(execution.objective_value)
        gold = finite_number(reference)
        matched = bool(objective is not None and gold is not None and (abs(objective - gold) <= self.objective_atol + self.objective_rtol * abs(gold)))
        success = bool(execution.code_executable and execution.solver_status_normalized == 'Optimal' and matched)
        return execution.model_copy(update={'objective_match': matched, 'solution_success': success, 'strict_success': success, 'optimality_gap': self._gap(objective, gold, execution.solver_status_normalized)})

    def execute(self, code_path: str | Path, gold_objective_value: float | None=None) -> ExecutionResult:
        self.last_execution_seconds = None
        started = perf_counter()
        try:
            absolute_code = Path(code_path).resolve()
            working_directory = None
            if absolute_code.is_file():
                working_directory = absolute_code.parent / (absolute_code.stem + '_workdir')
                working_directory.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run([sys.executable, str(absolute_code)], cwd=working_directory, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=self.code_timeout)
            stdout = completed.stdout or ''
            stderr = completed.stderr or ''
            record = parse_solver_record(stdout)
            objective = record['objective'] if record else finite_number(self._extract_objective(stdout))
            status = str(record['status']) if record else self._extract_status(stdout)
            status_normalized = record['normalized_status'] if record else self._normalize_solver_status(status, stdout)
            if not record and status_normalized == 'Optimal' and ('pulp' in legacy_backend(stdout).lower()):
                status_normalized = 'OptimalityUnverified'
            record = record or {'result_protocol': 'legacy_labels', 'backend': legacy_backend(stdout)}
            variable_values = record.get('variables', self._extract_variable_values(stdout))
            gap = self._gap(objective, gold_objective_value, status_normalized)
            objective_parsed = objective is not None
            objective_match = objective is not None and finite_number(gold_objective_value) is not None and (abs(objective - gold_objective_value) <= self.objective_atol + self.objective_rtol * abs(gold_objective_value))
            pipeline_success = completed.returncode == 0
            solution_success = pipeline_success and status_normalized == 'Optimal' and (objective is not None) and (gold_objective_value is not None) and objective_match
            return ExecutionResult(solver_record=record, code_executable=pipeline_success, solver_status=status, solver_status_normalized=status_normalized, stdout=stdout, stderr=stderr, returncode=completed.returncode, objective_value=objective, optimality_gap=gap, variable_values=variable_values, objective_parsed=objective_parsed, objective_match=objective_match, pipeline_success=pipeline_success, solution_success=solution_success, strict_success=solution_success)
        except subprocess.TimeoutExpired as exc:
            self.last_execution_seconds = perf_counter() - started
            return ExecutionResult(code_executable=False, solver_status='timeout', solver_status_normalized='Timeout', stdout=(exc.stdout.decode('utf-8', errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout) or '', stderr='Execution timed out.', returncode=None, objective_parsed=False, objective_match=False, pipeline_success=False, solution_success=False, strict_success=False)
        except Exception as exc:
            self.last_execution_seconds = perf_counter() - started
            return ExecutionResult(code_executable=False, solver_status='execution_error', solver_status_normalized='ExecutionError', stdout='', stderr=str(exc), returncode=None, objective_parsed=False, objective_match=False, pipeline_success=False, solution_success=False, strict_success=False)
        finally:
            self.last_execution_seconds = perf_counter() - started

    @staticmethod
    def fef_accuracy(fef_text: str) -> float:
        return Evaluator.evaluate_fef(fef_text)['fef_format_accuracy']

    @staticmethod
    def _extract_objective(stdout: str) -> float | None:
        number = '([-+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][-+]?\\d+)?)'
        labels = ['Objective Value', 'Objective value', 'Total Cost', 'Total Profit', 'Optimal Value', 'Objective']
        line_matches = []
        for line in stdout.splitlines():
            stripped = line.strip()
            for label in labels:
                match = re.match(f'^{re.escape(label)}\\s*[:=]\\s*{number}\\b', stripped, flags=re.IGNORECASE)
                if match:
                    line_matches.append(float(match.group(1)))
                    break
        if line_matches:
            return line_matches[-1]
        patterns = [f'{label}\\s*[:=]\\s*{number}' for label in labels]
        matches = []
        for pattern in patterns:
            matches.extend((float(match.group(1)) for match in re.finditer(pattern, stdout, flags=re.IGNORECASE)))
        if matches:
            return matches[-1]
        return None

    @staticmethod
    def _extract_status(stdout: str) -> str:
        patterns = ['^\\s*Solver Status\\s*:\\s*([A-Za-z0-9_ -]+)', '^\\s*Status\\s*:\\s*([A-Za-z0-9_ -]+)', '^\\s*Result\\s*-\\s*([A-Za-z0-9_ -]+)']
        for pattern in patterns:
            matches = list(re.finditer(pattern, stdout, flags=re.IGNORECASE | re.MULTILINE))
            if matches:
                return matches[-1].group(1).strip()
        return 'unknown'

    @staticmethod
    def _normalize_solver_status(status: str, output_text: str) -> str:
        return normalize_status(status, backend=legacy_backend(output_text))

    @staticmethod
    def _extract_variable_values(stdout: str) -> dict[str, float]:
        values = {}
        pattern = '^\\s*([A-Za-z_][A-Za-z0-9_()[\\],.-]*)\\s*=\\s*([-+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][-+]?\\d+)?)\\s*$'
        for line in stdout.splitlines():
            match = re.match(pattern, line.strip())
            if match:
                values[match.group(1)] = float(match.group(2))
        return values

    @staticmethod
    def _gap(objective: float | None, gold: float | None, solver_status_normalized: str='unknown') -> float | None:
        if solver_status_normalized != 'Optimal' or objective is None or gold is None:
            return None
        denom = max(abs(gold), 1e-09)
        return abs(objective - gold) / denom
