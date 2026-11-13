"""Tests for the vectorised engine and metrics. Offline; run: python -m unittest test_quant -v"""
import unittest

import numpy as np

import ai_bust_models as D
import ai_bust_probability as P
from quant import contagion_vec as V, data as qdata, engine, metrics, surrogate_f


class VectorisedModelD(unittest.TestCase):
    def test_matches_scalar_reference_draw_by_draw(self):
        rng = np.random.default_rng(7)
        sh = rng.uniform(0, 0.56, 60)
        p = V.draw_parameters(sh, rng)
        o = V.simulate_chunk(sh, p)
        for i in range(60):
            d = D.run_contagion(sh[i], p["accel"][i], p["distress_cut"][i], p["lgd"][i], p["fire_sale"][i],
                                p["buffer_scale"][i], p["lab_funding_freeze"][i], p["refi_sens"][i])
            self.assertAlmostEqual(d["credit_losses"], o["credit_loss_usd_bn"][i], places=8)
            ad = D.equity_drawdown(d, p["valuation_reset"][i], sh[i])
            self.assertAlmostEqual(ad, o["ai_equity_dd"][i], places=10)
            self.assertEqual("Neoclouds" in d["defaulted"], bool(o["neocloud_default"][i]))

    def test_output_is_continuous_not_binary(self):
        sf = np.random.default_rng(0).beta(1, 6, 5000)
        d = engine.run_model_d(sf, 0.3, n=2000, seed=3, n_jobs=1)
        self.assertGreater(len(np.unique(np.round(d["credit_loss_usd_bn"], 3))), 500)

    def test_same_result_for_any_worker_count(self):
        sf = np.random.default_rng(0).beta(1, 6, 5000)
        a = engine.run_model_d(sf, 0.3, n=1000, seed=3, n_jobs=1)["credit_loss_usd_bn"]
        b = engine.run_model_d(sf, 0.3, n=1000, seed=3, n_jobs=2)["credit_loss_usd_bn"]
        np.testing.assert_array_equal(a, b)

    def test_shock_sampler_pins_bust_probability(self):
        sf = np.random.default_rng(0).beta(1, 4, 20000)
        sh = V.draw_shocks(sf, 0.25, np.random.default_rng(1), 40000)
        self.assertAlmostEqual(float(np.mean(sh >= 0.15)), 0.25, delta=0.01)


class Metrics(unittest.TestCase):
    def test_var_cvar_ev(self):
        x = np.arange(1, 1001, dtype=float)
        m = metrics.risk_metrics(x)
        self.assertAlmostEqual(m["ev"], 500.5)
        self.assertAlmostEqual(m["var95"], np.quantile(x, 0.95))
        self.assertAlmostEqual(m["cvar95"], x[x >= m["var95"]].mean())
        self.assertGreater(m["cvar95"], m["var95"])
        self.assertEqual(sum(m["histogram"]["counts"]) + m["histogram"]["overflow"], 1000)
        self.assertEqual(len(m["histogram"]["edges"]), len(m["histogram"]["counts"]) + 1)

    def test_degenerate_input_does_not_crash(self):
        m = metrics.risk_metrics(np.zeros(500))
        self.assertEqual(m["cvar95"], 0.0)
        self.assertEqual(m["p_zero"], 1.0)


class Emulator(unittest.TestCase):
    def test_heldout_skill(self):
        import json, os
        d = json.load(open(os.path.join(surrogate_f.HERE, "f_training.json")))
        rep = surrogate_f.FEmulator.cross_validate(d["rows"], d["param_priors"])
        self.assertGreater(rep["sp500_dd"]["r2_heldout"], 0.9)
        self.assertGreater(rep["ai_dd"]["r2_heldout"], 0.9)
        self.assertGreater(rep["sov_spend"]["r2_heldout"], 0.8)
        for o in rep.values():                                   # sampled tail must stay close to the real tail
            self.assertLess(abs(o["p95_emulated"] / o["p95_real"] - 1), 0.15)

    def test_outputs_in_range(self):
        em, _ = surrogate_f.load()
        o = em.sample(np.linspace(0, 0.56, 3000), np.random.default_rng(0))
        for k in ("sp500_dd", "ai_dd"):
            self.assertTrue(((o[k] >= 0) & (o[k] <= 0.95)).all())
        self.assertTrue((o["sov_spend"] >= 0).all() and (o["credit_loss"] >= 0).all())


class LiveMapping(unittest.TestCase):
    paper = {"r_free": 0.044, "sigma": (0.32, 0.45), "sox_drawdown": (0.12, 0.22), "nc_spread": (0.045, 0.065), "oracle_cds": 0.0227}

    def test_feeds_map_to_live_inputs(self):
        feeds = {"smh": {"rv30": 0.5, "iv30": 0.4, "drawdown_from_peak": 0.2},
                 "hy": {"value": 3.5, "ref_value": 3.0}, "tbill": {"value": 4.0}}
        live, prov = qdata.to_live_overrides(feeds, self.paper)
        self.assertEqual(live["sigma"], (0.4, 0.56))
        self.assertEqual(live["sox_drawdown"], (0.11, 0.21))
        self.assertEqual(live["nc_spread"], (0.05, 0.07))      # +50 bp
        self.assertEqual(live["r_free"], 0.04)

    def test_failed_feeds_fall_back_and_say_so(self):
        live, prov = qdata.to_live_overrides({"smh": None, "hy": None, "tbill": None}, self.paper)
        self.assertEqual(live, self.paper)
        self.assertTrue(all("paper default" in prov[k] for k in ("sigma", "nc_spread", "r_free")))




class AgentReadable(unittest.TestCase):
    def test_summary_and_page(self):
        import json, os, unified_site as U
        here = os.path.dirname(os.path.abspath(__file__))
        run = json.load(open(os.path.join(here, "public", "data", "latest_run.json")))
        md = U.summary_md(run)
        self.assertIn("CVaR95", md)
        self.assertIn(f"{100 * run['odds']['economic_bust']['end-2028']['median']:.0f}%", md)
        page = U.index_html(here)
        self.assertIn('"@type": "Dataset"', page)
        self.assertIn("<noscript>", page)
        self.assertNotIn("<!--SSR-->", page)
        json.dumps(U.DATA_DICTIONARY)


if __name__ == "__main__":
    unittest.main()
