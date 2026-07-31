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
    settings = {
        "enabled": True,
        "shed_threshold_kw": 3.0,
        "restore_threshold_kw": 2.0,
        "confirm_samples": 3,
        "min_action_interval_seconds": 30.0,
    }
    settings.update(overrides)

    clock = FakeClock()
    return LoadSheddingController(LoadSheddingConfig(**settings), clock=clock), clock


def feed(controller, power_w: float, times: int):
    """Ayni yuku birkac kez uygular ve uretilen kararlari dondurur.

    Aksiyon dogrulama penceresi dolar dolmaz uretildigi icin sonuncu karara
    bakmak yaniltici olur; testler uretilen kararlarin tamamina bakar.
    """
    return [controller.evaluate(power_w) for _ in range(times)]


def test_disabled_controller_never_acts():
    controller, _ = build(enabled=False)

    decisions = feed(controller, 9999.0, times=10)

    assert all(item.action == "HOLD" for item in decisions)
    assert all(item.command is None for item in decisions)
    assert controller.shed_active is False


def test_requires_consecutive_samples_before_shedding():
    """Anlik bir sicrama yuku kesmemeli."""
    controller, _ = build()

    decisions = feed(controller, 4000.0, times=3)

    assert [item.action for item in decisions] == ["HOLD", "HOLD", "SHED"]
    assert decisions[-1].command == "SHED_LOAD"
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

    feed(controller, 4000.0, times=3)
    assert controller.shed_active is True

    clock.advance(60.0)
    # 2.5 kW: kesme esiginin altinda ama geri verme esiginin ustunde.
    decisions = feed(controller, 2500.0, times=5)

    assert all(item.reason == "within_hysteresis_band" for item in decisions)
    assert all(item.command is None for item in decisions)
    assert controller.shed_active is True


def test_restores_when_load_drops_below_restore_threshold():
    controller, clock = build()

    feed(controller, 4000.0, times=3)
    assert controller.shed_active is True

    clock.advance(60.0)
    decisions = feed(controller, 1000.0, times=3)

    # Dogrulama penceresi dolana kadar beklenir, sonra tek bir aksiyon uretilir.
    assert [item.action for item in decisions] == ["HOLD", "HOLD", "RESTORE"]
    assert decisions[-1].command == "CONNECT_LOAD"
    assert controller.shed_active is False


def test_minimum_interval_blocks_rapid_toggling():
    """Role komutlari arasinda asgari sure gecmeden yeni komut uretilmez."""
    controller, clock = build()

    for _ in range(3):
        controller.evaluate(4000.0)
    assert controller.shed_active is True

    # Sure dolmadan yuk dustu: geri verme ertelenmeli.
    clock.advance(5.0)
    blocked = feed(controller, 500.0, times=5)

    assert all(item.action == "HOLD" for item in blocked)
    assert any(item.reason == "min_interval_not_elapsed" for item in blocked)
    assert controller.shed_active is True

    # Sure dolunca ilk olcumde geri verilir.
    clock.advance(30.0)
    allowed = feed(controller, 500.0, times=3)

    assert [item.action for item in allowed].count("RESTORE") == 1
    assert allowed[0].action == "RESTORE"
    assert controller.shed_active is False


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
