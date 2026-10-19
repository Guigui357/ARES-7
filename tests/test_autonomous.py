#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes do ARES-7: motor autonomo, validacao e daemon.

Roda sem rede, sem LLM e sem hardware: o LLM e mockado e as leituras de
sistema sao simuladas.

    python3 -m unittest discover -s tests -v
    python3 tests/test_autonomous.py
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.autonomous import AutonomousAres  # noqa: E402
from core.config import ARES7_HOME, Config  # noqa: E402
from core.daemon import AutonomousDaemon  # noqa: E402
from core.router import Utterance, safe_calc  # noqa: E402
from core.watcher import Observation  # noqa: E402

GB = 1024 ** 3
PENDING_PATH = os.path.join(ARES7_HOME, "autonomous_pending.json")


def remove_pending() -> None:
    if os.path.isfile(PENDING_PATH):
        os.remove(PENDING_PATH)


class FakeLLM:
    """LLM mockado: devolve sempre a mesma resposta."""

    def __init__(self, reply: str = "") -> None:
        self.reply = reply
        self.calls: list[list[dict]] = []

    def probe(self):
        return True, "fake-model", None

    def ensure_online(self, wait_seconds: float = 45.0):
        return True, "fake-model"

    def reconnect(self):
        return True, "fake-model"

    def chat(self, messages):
        self.calls.append(messages)
        return self.reply


def make_config(**daemon) -> Config:
    config = Config()
    config.set("llm", "autostart", False)
    for key, value in daemon.items():
        config.set("daemon", key, value)
    return config


def make_engine(reply: str = "", **daemon) -> AutonomousAres:
    engine = AutonomousAres(config=make_config(**daemon))
    engine.speak_enabled = False
    engine.llm = FakeLLM(reply)
    return engine


# ============================================================================
# Deteccao de intencao (router local, zero LLM)
# ============================================================================

class TestDeteccao(unittest.TestCase):
    """O router local precisa reconhecer o pedido sem acordar o LLM."""

    def setUp(self) -> None:
        remove_pending()
        self.engine = make_engine()

    def tearDown(self) -> None:
        remove_pending()

    def _reply(self, text: str) -> str:
        return self.engine.run_autonomous(text).splitlines()[0]

    def test_sistema(self):
        self.assertIn("Sistema:", self._reply("verifique o sistema"))

    def test_sistema_sinonimos(self):
        for frase in ("como esta o sistema", "status do sistema", "panorama do notebook"):
            with self.subTest(frase=frase):
                self.assertIn("Sistema:", self._reply(frase))

    def test_calculo_simples(self):
        self.assertIn("4", self._reply("quanto eh 2+2"))

    def test_calculo_porcento(self):
        self.assertIn("30", self._reply("quanto eh 15 por cento de 200"))

    def test_calculo_por_extenso(self):
        self.assertIn("4", self._reply("quanto eh dois mais dois"))

    def test_nota(self):
        self.assertIn("Anotado", self._reply("anote comprar pao"))

    def test_memoria(self):
        self.assertIn("Guardei", self._reply("lembra que meu projeto se chama Ares"))

    def test_memoria_generica(self):
        self._reply("lembra que meu projeto se chama Ares")
        self.assertIn("lembro", self._reply("o que voce lembra?").lower())

    def test_acao_de_risco_pendente(self):
        reply = self._reply("desligar o computador")
        self.assertIn("Tem certeza", reply)

    def test_timer(self):
        self.assertIn("Timer", self._reply("timer de 5 minutos"))

    def test_busca_arquivo_vence_busca_web(self):
        reply = self._reply("busque arquivo AGENTS.md")
        self.assertNotIn("xdg-open", reply)

    def test_busca_web_mantida(self):
        reply = self._reply("pesquise arquivos de poker")
        self.assertIn("xdg-open", reply)

    def test_pasta_explicita(self):
        self.assertIn("/tmp", self._reply("liste a pasta /tmp"))


# ============================================================================
# Validacao: nada de executar o que nao da certo
# ============================================================================

class TestValidacao(unittest.TestCase):
    """A validacao barra parametros invalidos e dependencias ausentes."""

    def setUp(self) -> None:
        self.engine = make_engine()

    def test_valor_de_volume_invalido(self):
        v = self.engine._validate("volume", {"step": "abc"})
        self.assertFalse(v["ok"])
        self.assertIn("invalido", v["reason"])

    def test_parametro_obrigatorio(self):
        v = self.engine._validate("volume", {})
        self.assertFalse(v["ok"])
        self.assertIn("step", v["reason"])

    def test_modo_de_mudo_invalido(self):
        v = self.engine._validate("mute", {"mode": "xyz"})
        self.assertFalse(v["ok"])

    def test_acao_de_midia_invalida(self):
        v = self.engine._validate("media", {"action": "dance"})
        self.assertFalse(v["ok"])

    def test_url_invalida(self):
        v = self.engine._validate("open_url", {"url": "nao-e-url"})
        self.assertFalse(v["ok"])

    def test_site_desconhecido(self):
        v = self.engine._validate("open_site", {"name": "site-que-nao-existe"})
        self.assertFalse(v["ok"])

    def test_caminho_inexistente(self):
        v = self.engine._validate("list_dir", {"path": "/caminho/que/nao/existe"})
        self.assertFalse(v["ok"])

    def test_ferramenta_desconhecida(self):
        reply = make_engine('{"actions": [{"tool": "nao_existe", "params": {}}], "reply": ""}') \
            .run_autonomous("faca algo")
        self.assertIn("nao encontrada", reply)

    def test_acao_de_risco_exige_confirmacao(self):
        v = self.engine._validate("poweroff", {})
        self.assertFalse(v["ok"])
        self.assertTrue(v.get("needs_confirm"))

    def test_calculadora_segura(self):
        self.assertEqual(safe_calc("2+2"), 4)
        with self.assertRaises(ValueError):
            safe_calc("__import__('os').system('ls')")


# ============================================================================
# Planejamento com LLM
# ============================================================================

class TestPlanejamento(unittest.TestCase):
    """O plano do LLM e executado em sequencia, com validacao em cada passo."""

    # Frase que o router local nao resolve: vai mesmo pelo planejador.
    PEDIDO = "me ajuda com a lista de compras de amanha"

    def test_executa_acao_planejada(self):
        engine = make_engine('{"actions": [{"tool": "system_info", "params": {}}], "reply": ""}')
        self.assertIn("Sistema:", engine.run_autonomous(self.PEDIDO))

    def test_resposta_conversacional(self):
        engine = make_engine('{"actions": [], "reply": "Sou o ARES-7, offline."}')
        self.assertIn("offline", engine.run_autonomous("quem e voce?"))

    def test_aceita_lista_simples(self):
        engine = make_engine('[{"tool": "system_info", "params": {}}]')
        self.assertIn("Sistema:", engine.run_autonomous(self.PEDIDO))

    def test_aceita_bloco_markdown(self):
        engine = make_engine('```json\n{"actions": [{"tool": "system_info", "params": {}}], "reply": ""}\n```')
        self.assertIn("Sistema:", engine.run_autonomous(self.PEDIDO))

    def test_resposta_nao_json_vira_conversa(self):
        engine = make_engine("apenas um texto")
        self.assertIn("apenas um texto", engine.run_autonomous("fale comigo"))

    def test_llm_offline_nao_quebra(self):
        engine = make_engine()
        engine.llm.probe = lambda: (False, None, "offline")
        engine.llm.ensure_online = lambda wait_seconds=45.0: (False, None)
        reply = engine.run_autonomous(self.PEDIDO)
        self.assertTrue(reply)

    def test_uma_unica_chamada_de_llm(self):
        engine = make_engine('{"actions": [{"tool": "system_info", "params": {}}], "reply": ""}')
        engine.run_autonomous(self.PEDIDO)
        self.assertEqual(len(engine.llm.calls), 1)


# ============================================================================
# Daemon: observa, decide e age sem mensagem
# ============================================================================

class TestDaemon(unittest.TestCase):
    """O daemon age sozinho e fica quieto quando nao ha nada novo."""

    def setUp(self) -> None:
        remove_pending()
        self.daemon = AutonomousDaemon(config=make_config(llm_decisions=False))
        self.daemon.speak_enabled = False

    def tearDown(self) -> None:
        remove_pending()

    def _fix(self, obs: Observation) -> None:
        self.daemon.watcher._all = lambda: [obs]

    def test_silencio_sem_nada_a_fazer(self):
        self.daemon.watcher._all = lambda: []
        self.assertEqual(self.daemon.tick(), [])

    def test_acao_segura_executa_sozinha(self):
        self._fix(Observation(key="mem", title="Memoria", detail="baixa",
                              severity="warn", tool="reset_context"))
        msgs = self.daemon.tick()
        self.assertTrue(msgs)
        self.assertIn("Contexto da conversa limpo", msgs[0])

    def test_acao_de_risco_vai_para_a_fila(self):
        self._fix(Observation(key="risco", title="Risco", detail="d",
                              severity="warn", tool="poweroff"))
        msgs = self.daemon.tick()
        self.assertIn("confirmacao", msgs[0])
        self.assertTrue(os.path.isfile(PENDING_PATH))
        with open(PENDING_PATH, "r", encoding="utf-8") as handle:
            state = json.load(handle)
        self.assertEqual(state["tool"], "poweroff")
        self.assertEqual(state["mode"], "step")

    def test_nao_repete_a_mesma_observacao(self):
        obs = Observation(key="x", title="X", detail="d", severity="warn",
                          tool="reset_context")
        self._fix(obs)
        self.assertTrue(self.daemon.tick())
        self.assertEqual(self.daemon.tick(), [])

    def test_cooldown_segura_repeticao(self):
        self.daemon = AutonomousDaemon(config=make_config(llm_decisions=False,
                                                           report_cooldown=999))
        obs = Observation(key="y", title="Y", detail="d", severity="warn",
                          tool="reset_context")
        self._fix(obs)
        self.daemon.tick()
        self.daemon.watcher._seen.clear()
        self.assertEqual(self.daemon.tick(), [])

    def test_ferramenta_notify(self):
        self.assertEqual(self.daemon.engine._notify("opa"), "opa")

    def test_registra_no_historico(self):
        self._fix(Observation(key="z", title="Z", detail="d", severity="warn",
                              tool="reset_context"))
        self.daemon.tick()
        self.assertEqual(len(self.daemon.history()), 1)


# ============================================================================
# Regras de deteccao do observador
# ============================================================================

class TestWatcher(unittest.TestCase):
    """As condicoes do sistema viram observacoes com a severidade certa."""

    def setUp(self) -> None:
        import core.watcher as watcher
        self.watcher = watcher
        self.original = {
            "read_memory": watcher.read_memory,
            "read_battery": watcher.read_battery,
            "read_temperature": watcher.read_temperature,
            "disk_usage": watcher.shutil.disk_usage,
        }

    def tearDown(self) -> None:
        self.watcher.read_memory = self.original["read_memory"]
        self.watcher.read_battery = self.original["read_battery"]
        self.watcher.read_temperature = self.original["read_temperature"]
        self.watcher.shutil.disk_usage = self.original["disk_usage"]

    def test_memoria_critica(self):
        self.watcher.read_memory = lambda: (8.9 * GB, 9.2 * GB)
        obs = self.watcher.Watcher()._memory()
        self.assertEqual(obs[0].key, "memoria_critica")
        self.assertEqual(obs[0].severity, "critical")

    def test_memoria_normal_nao_avisa(self):
        self.watcher.read_memory = lambda: (2 * GB, 9.2 * GB)
        self.assertEqual(self.watcher.Watcher()._memory(), [])

    def test_bateria_baixa(self):
        self.watcher.read_battery = lambda: "15% (Discharging)"
        obs = self.watcher.Watcher()._battery()
        self.assertEqual(obs[0].key, "bateria_baixa")

    def test_temperatura_alta(self):
        self.watcher.read_temperature = lambda: 84.0
        obs = self.watcher.Watcher()._temperature()
        self.assertEqual(obs[0].key, "temperatura_alta")

    def test_disco_baixo(self):
        class Usage:
            used, free, total = 88 * GB, 8 * GB, 96 * GB
        self.watcher.shutil.disk_usage = lambda p: Usage()
        obs = self.watcher.Watcher()._disk()
        self.assertEqual(obs[0].key, "disco_baixo")


# ============================================================================
# Configuracao
# ============================================================================

class TestConfig(unittest.TestCase):
    """As secoes novas existem nos defaults e aceitam variaveis de ambiente."""

    def test_secao_autonomous(self):
        config = Config()
        self.assertIn("autonomous", config.data)
        self.assertTrue(config.get("autonomous", "enabled", False))

    def test_secao_daemon(self):
        config = Config()
        self.assertIn("daemon", config.data)
        self.assertEqual(config.get("daemon", "interval"), 60)

    def test_variavel_de_ambiente_inteira(self):
        os.environ["ARES7_DAEMON_INTERVAL"] = "42"
        try:
            config = Config()
            self.assertEqual(config.get("daemon", "interval"), 42)
        finally:
            del os.environ["ARES7_DAEMON_INTERVAL"]

    def test_variavel_de_ambiente_booleana(self):
        os.environ["ARES7_DAEMON_ACTIONS"] = "false"
        try:
            config = Config()
            self.assertFalse(config.get("daemon", "auto_actions", True))
        finally:
            del os.environ["ARES7_DAEMON_ACTIONS"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
