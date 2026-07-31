import pytest

from smart_energy.config import LoadSheddingConfig
from smart_energy.load_shedding import LoadSheddingController


class FakeClock:
    """Testlerin gercek zamanda beklemesini onlemek icin elle ilerletilen saat."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def build(**overrides):
    config = LoadSheddingConfig(
        enabled=True,
        shed_threshold_kw=3.0,
        restore_threshold_kw=2.0,
        confirm_samples=3,
        min_action_interval_seconds=30.0,
        **overrides,
    )
    clock = FakeClock()
    return LoadSheddingController(config, clock=clock), clock


def test_disabled_controller_never_acts():
    controller, _ = build(enabled=False)

    for _ in range(10):
        decision = controller.evaluate(9999.0)

    assert decision.action == "HOLD"
    assert decision.command is None
    assert controller.shed_active is False


def test_requires_consecutive_samples_before_shedding():
    """Anlik bir sicrama yuku kesmemeli."""
    controller, _ = build()

    assert controller.evaluate(4000.0).command is None  # 1
    assert controller.evaluate(4000.0).command is None  # 2
    decision = controller.evaluate(4000.0)  # 3 -> aksiyon

    assert decision.action == "SHED"
    assert decision.command == "SHED_LOAD"
    assert controller.shed_active is True


def test_single_spike_does_not_trigger():
    """Ust uste olmayan esik asimlari sayaci sifirlar."""
    controller, _ = build()

    controller.evaluate(4000.0)
    controller.evaluate(4000.0)
    controller.evaluate(500.0)  # normale dondu, sayac sifirlanir
    decision = controller.evaluate(4000.0)

    assert decision.command is None
    assert controller.shed_active is False


def test_hysteresis_band_holds_state():
    """Iki esik arasindaki bolgede hicbir aksiyon alinmaz."""
    controller, clock = build()

    for _ in range(3):
        controller.evaluate(4000.0)
    assert controller.shed_active is True

    clock.advance(60.0)
    # 2.5 kW: kesme esiginin altinda ama geri verme esiginin ustunde.
    for _ in range(5):
        decision = controller.evaluate(2500.0)

    assert decision.reason == "within_hysteresis_band"
    assert controller.shed_active is True


def test_restores_when_load_drops_below_restore_threshold():
    controller, clock = build()

    for _ in range(3):
        controller.evaluate(4000.0)
    assert controller.shed_active is True

    clock.advance(60.0)
    controller.evaluate(1000.0)
    controller.evaluate(1000.0)
    decision = controller.evaluate(1000.0)

    assert decision.action == "RESTORE"
    assert decision.command == "CONNECT_LOAD"
    assert controller.shed_active is False


def test_minimum_interval_blocks_rapid_toggling():
    """Role komutlari arasinda asgari sure gecmeden yeni komut uretilmez."""
    controller, clock = build()

    for _ in range(3):
        controller.evaluate(4000.0)
    assert controller.shed_active is True

    # Sure dolmadan yuk dustu: geri verme ertelenmeli.
    clock.advance(5.0)
    for _ in range(5):
        decision = controller.evaluate(500.0)

    assert decision.reason == "min_interval_not_elapsed"
    assert controller.shed_active is True

    clock.advance(30.0)
    for _ in range(3):
        decision = controller.evaluate(500.0)

    assert decision.action == "RESTORE"


def test_rejects_configuration_without_hysteresis():
    """restore >= shed olsaydi role esik civarinda surekli acilip kapanirdi."""
    with pytest.raises(ValueError):
        LoadSheddingController(
            LoadSheddingConfig(enabled=True, shed_threshold_kw=3.0, restore_threshold_kw=3.0)
        )

    with pytest.raises(ValueError):
        LoadSheddingController(
            LoadSheddingConfig(enabled=True, shed_threshold_kw=3.0, restore_threshold_kw=4.0)
        )


def test_rejects_invalid_confirm_samples():
    with pytest.raises(ValueError):
        LoadSheddingController(LoadSheddingConfig(enabled=True, confirm_samples=0))
