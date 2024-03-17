import logging
import subprocess

from dmoj.checkers import CheckerOutput
from dmoj.cptbox import TracedPopen
from dmoj.error import OutputLimitExceeded
from dmoj.executors import executors
from dmoj.executors.base_executor import BaseExecutor
from dmoj.graders.base import BaseGrader
from dmoj.problem import TestCase
from dmoj.result import CheckerResult, Result

log = logging.getLogger('dmoj.graders')


class StandardGrader(BaseGrader):
    def grade(self, case: TestCase) -> Result:
        result = Result(case)

        input = case.input_data()  # cache generator data

        # If a case execution time is close to time limit and TLE'd,
        # retry it upto 3 times
        time_limit = case.problem.time_limit
        execution_time_upper = time_limit + 0.5
        retry_count = 3
        while retry_count > 0:
            self._launch_process(case)
            error = self._interact_with_process(case, result, input)
            process = self._current_proc

            if process.is_tle and process.execution_time < execution_time_upper:
                process.kill()
                log.info('Retry TLE %.3fs (within 0.5s of time limit %.3fs)', process.execution_time, time_limit)
                retry_count -= 1
            else:
                break

        process = self._current_proc

        assert process is not None
        self.populate_result(error, result, process)

        check = self.check_result(case, result)

        # checkers must either return a boolean (True: full points, False: 0 points)
        # or a CheckerResult, so convert to CheckerResult if it returned bool
        if not isinstance(check, CheckerResult):
            check = CheckerResult(check, case.points if check else 0.0)

        result.result_flag |= [Result.WA, Result.AC][check.passed]
        result.points = check.points
        result.feedback = check.feedback or result.feedback
        result.extended_feedback = check.extended_feedback or result.extended_feedback

        case.free_data()

        return result

    def populate_result(self, error: bytes, result: Result, process: TracedPopen) -> None:
        self.binary.populate_result(error, result, process)

    def check_result(self, case: TestCase, result: Result) -> CheckerOutput:
        # If the submission didn't crash and didn't time out, there's a chance it might be AC
        # We shouldn't run checkers if the submission is already known to be incorrect, because some checkers
        # might be very computationally expensive.
        # See https://github.com/DMOJ/judge/issues/170
        checker = case.checker()
        # checker is a `partial` object, NOT a `function` object
        if not result.result_flag or getattr(checker.func, 'run_on_error', False):
            try:
                check = checker(
                    result.proc_output,
                    case.output_data(),
                    submission_source=self.source,
                    judge_input=case.input_data(),
                    point_value=case.points,
                    case_position=case.position,
                    batch=case.batch,
                    submission_language=self.language,
                    binary_data=case.has_binary_data,
                    execution_time=result.execution_time,
                    problem_id=self.problem.id,
                    result=result,
                )
            except UnicodeDecodeError:
                # Don't rely on problemsetters to do sane things when it comes to Unicode handling, so
                # just proactively swallow all Unicode-related checker errors.
                return CheckerResult(False, 0, feedback='invalid unicode')
        else:
            # Solution is guaranteed to receive 0 points
            check = False

        return check

    def _launch_process(self, case: TestCase) -> None:
        self._current_proc = self.binary.launch(
            time=self.problem.time_limit,
            memory=self.problem.memory_limit,
            file_io=case.config.file_io,
            symlinks=case.config.symlinks,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            wall_time=case.config.wall_time_factor * self.problem.time_limit,
        )

    def _interact_with_process(self, case: TestCase, result: Result, input: bytes) -> bytes:
        process = self._current_proc
        assert process is not None
        try:
            result.proc_output, error = process.communicate(
                input, outlimit=case.config.output_limit_length, errlimit=1048576
            )
        except OutputLimitExceeded:
            error = b''
            process.kill()
        finally:
            process.wait()
        return error

    def _generate_binary(self) -> BaseExecutor:
        return executors[self.language].Executor(
            self.problem.id,
            self.source,
            hints=self.problem.config.hints or [],
            unbuffered=self.problem.config.unbuffered,
            meta=self.problem.config.meta or {},
        )
