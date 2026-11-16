"""testdata/openapi.yaml is a copy of the API description in the panel repository (scripts/sync-spec.sh). These
tests fail when the API gains a call this library does not have, or an ability it does not know, so the library
cannot quietly fall behind. (A regular expression is enough: no YAML dependency.)"""

import os
import re
import unittest

import helpers  # noqa: F401  (puts src on the path)

from commypanel import Ability, Client, DeployStrategy

SPEC = os.path.join(helpers.HERE, "..", "testdata", "openapi.yaml")

# The Client method that implements each operation of the spec.
METHOD_OF = {
    "getToken": "token",
    "listApps": "list_apps",
    "getApp": "get_app",
    "listDeployments": "list_deployments",
    "startDeployment": "start_deployment",
    "getDeployment": "get_deployment",
    "applyChanges": "apply_changes",
    "startApp": "start_app",
    "stopApp": "stop_app",
    "restartApp": "restart_app",
    "getLogs": "logs",
    "listEnv": "list_env",
    "setEnv": "set_env",
    "unsetEnv": "unset_env",
}


def spec_text():
    with open(SPEC, encoding="utf-8") as handle:
        return handle.read()


class ContractTests(unittest.TestCase):
    def test_every_operation_of_the_spec_has_a_method(self):
        ids = re.findall(r"(?m)^\s+operationId:\s*(\w+)\s*$", spec_text())
        self.assertGreaterEqual(len(ids), 14, "found only %d operations in the spec" % len(ids))

        for operation in ids:
            self.assertIn(operation, METHOD_OF, "the spec has the operation %r and this library has no method for it" % operation)
            self.assertTrue(callable(getattr(Client, METHOD_OF[operation], None)), "Client.%s does not exist" % METHOD_OF[operation])

        for operation in METHOD_OF:
            self.assertIn(operation, ids, "the library maps %r, which is no longer in the spec" % operation)

    def test_the_specs_abilities_are_the_librarys(self):
        known = {Ability.READ, Ability.DEPLOY, Ability.CONTROL, Ability.LOGS, Ability.ENV}
        used = set(re.findall(r"""(?m)x-ability:\s*['"]?([\w:]+)['"]?""", spec_text()))

        self.assertEqual(used, known)

    def test_the_specs_deploy_modes_are_the_librarys(self):
        text = spec_text()

        for mode in (DeployStrategy.ROLLING, DeployStrategy.STOP_FIRST):
            self.assertRegex(text, r"(?m)^\s+-\s*%s\s*$" % re.escape(mode))


if __name__ == "__main__":
    unittest.main()
