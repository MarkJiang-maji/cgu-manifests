import unittest

import prom_v2 as prom


class ParseQuantityTests(unittest.TestCase):
    def test_parse_cpu_quantity(self):
        self.assertEqual(prom.parse_cpu_quantity("500m"), 0.5)
        self.assertEqual(prom.parse_cpu_quantity("2"), 2.0)

    def test_parse_memory_to_gib_binary(self):
        self.assertAlmostEqual(prom.parse_memory_to_gib("1024Mi"), 1.0)
        self.assertAlmostEqual(prom.parse_memory_to_gib("1Gi"), 1.0)

    def test_parse_memory_to_gib_decimal(self):
        self.assertAlmostEqual(prom.parse_memory_to_gib("1G"), 1.0)
        self.assertAlmostEqual(prom.parse_memory_to_gib("2048M"), 2.0)

    def test_iter_gpu_resources(self):
        resources = dict(prom.iter_gpu_resources({"nvidia.com/gpu": "2", "cpu": "1"}))
        self.assertEqual(resources, {"nvidia.com/gpu": 2.0})


class DummyOwner:
    def __init__(self, kind, name, controller=True):
        self.kind = kind
        self.name = name
        self.controller = controller


class DummyMeta:
    def __init__(self, name, namespace="demo", labels=None, owner_references=None):
        self.name = name
        self.namespace = namespace
        self.labels = labels or {}
        self.owner_references = owner_references or []


class DummyStatus:
    def __init__(self, phase="Running"):
        self.phase = phase


class DummyPod:
    def __init__(self, name, namespace="demo", labels=None, owner_references=None, phase="Running"):
        self.metadata = DummyMeta(name, namespace, labels, owner_references)
        self.status = DummyStatus(phase)


class NotebookNameTests(unittest.TestCase):
    def test_identify_notebook_from_label(self):
        pod = DummyPod("x", labels={"notebook-name": "demo"})
        self.assertEqual(prom.identify_notebook_name(pod), "demo")

    def test_identify_notebook_requires_explicit_label(self):
        pod = DummyPod(
            "demo-0",
            owner_references=[DummyOwner("StatefulSet", "demo")],
        )
        self.assertIsNone(prom.identify_notebook_name(pod))

    def test_legacy_identify_notebook_name_uses_suffix(self):
        pod = DummyPod("openldap-0")
        self.assertEqual(prom.legacy_identify_notebook_name(pod), "openldap-0")

    def test_legacy_identify_notebook_name_rejects_non_suffix_name(self):
        pod = DummyPod("backend-abc")
        self.assertIsNone(prom.legacy_identify_notebook_name(pod))


class WorkloadIdentificationTests(unittest.TestCase):
    def test_normalize_replicaset_name(self):
        self.assertEqual(
            prom.normalize_replicaset_name("pvcviewer-a1-workspace-64ccf9ff6c"),
            "pvcviewer-a1-workspace",
        )

    def test_identify_workload_for_notebook(self):
        pod = DummyPod("notebook1-0", labels={"notebook-name": "notebook1"})
        self.assertEqual(
            prom.identify_workload(pod),
            ("notebook1", "StatefulSet", "notebook"),
        )

    def test_identify_workload_for_pvcviewer(self):
        pod = DummyPod(
            "pvcviewer-a1-workspace-64ccf9ff6c-78x56",
            labels={
                "app.kubernetes.io/instance": "pvcviewer-a1-workspace",
                "app.kubernetes.io/part-of": "pvc-viewer",
            },
            owner_references=[DummyOwner("ReplicaSet", "pvcviewer-a1-workspace-64ccf9ff6c")],
        )
        self.assertEqual(
            prom.identify_workload(pod),
            ("pvcviewer-a1-workspace", "Deployment", "pvcviewer"),
        )

    def test_identify_workload_for_deployment(self):
        pod = DummyPod(
            "backend-deployment-6ff76cd8cd-9nr2l",
            labels={"app": "backend"},
            owner_references=[DummyOwner("ReplicaSet", "backend-deployment-6ff76cd8cd")],
        )
        self.assertEqual(
            prom.identify_workload(pod),
            ("backend-deployment", "Deployment", "deployment"),
        )


class ProfileNamespaceTests(unittest.TestCase):
    def test_parse_profile_namespaces(self):
        profiles = [
            {"metadata": {"name": "b1144209"}},
            {"metadata": {"name": "wycctest1"}},
            {"metadata": {}},
        ]
        self.assertEqual(
            prom.parse_profile_namespaces(profiles),
            {"b1144209", "wycctest1"},
        )

    def test_should_track_only_profile_namespaces(self):
        profile_namespaces = {"b1144209", "wycctest1"}
        tracked_pod = DummyPod("notebook1-0", namespace="b1144209")
        system_pod = DummyPod("prometheus-0", namespace="prometheus")
        finished_pod = DummyPod("old-0", namespace="wycctest1", phase="Succeeded")

        self.assertTrue(prom.should_track_pod(tracked_pod, profile_namespaces))
        self.assertFalse(prom.should_track_pod(system_pod, profile_namespaces))
        self.assertFalse(prom.should_track_pod(finished_pod, profile_namespaces))


class LegacyBootstrapTests(unittest.TestCase):
    def test_bootstrap_derives_cost_time_when_missing(self):
        state = prom.LegacyCostState(
            cpu_cost={"b1144209": 120.0},
            gpu_cost={"b1128005": 50.0},
        )
        state.bootstrapped = True
        prom.build_snapshot([], [], [], [], 2.0, 10.0, state, now_monotonic=100.0)
        self.assertEqual(state.cpu_cost_time["b1144209"], 60.0)
        self.assertEqual(state.gpu_cost_time["b1128005"], 5.0)


if __name__ == "__main__":
    unittest.main()
