from __future__ import annotations

import unittest
from types import SimpleNamespace

from pydantic import BaseModel

from oracle_audit import evaluate_task


class Environment(BaseModel):
    value: int = 0


class Suite:
    name = "fixture"
    tools = []

    def load_and_inject_default_environment(self, injections):
        return Environment()


class Runtime:
    def __init__(self, tools):
        pass

    def run_function(self, environment, function, args):
        if function == "change":
            environment.value = 1
        return None, None


class Task:
    PROMPT = "Set the value."
    GROUND_TRUTH_OUTPUT = "done"

    @staticmethod
    def init_environment(environment):
        return environment

    @staticmethod
    def ground_truth(pre_environment):
        return [SimpleNamespace(function="change", args={})]

    @staticmethod
    def utility_from_traces(output, pre, post, calls):
        return None

    @staticmethod
    def utility(output, pre, post):
        return post.value == 1


class WeakTask(Task):
    @staticmethod
    def utility(output, pre, post):
        return True


class OracleAuditTests(unittest.TestCase):
    def test_sound_oracle_rejects_deleted_state_change(self):
        result = evaluate_task(Suite(), "user_task_0", Task(), "user", Runtime)
        self.assertTrue(result["full_reference_passes"])
        self.assertTrue(result["deletion_trials"][0]["execution_completed"])
        self.assertFalse(result["deletion_trials"][0]["oracle_still_passes"])

    def test_weak_oracle_accepts_deleted_state_change(self):
        result = evaluate_task(Suite(), "user_task_0", WeakTask(), "user", Runtime)
        self.assertTrue(result["deletion_trials"][0]["oracle_still_passes"])
        self.assertTrue(result["empty_execution_passes"])


if __name__ == "__main__":
    unittest.main()
