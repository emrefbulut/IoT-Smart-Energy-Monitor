from __future__ import annotations

from dataclasses import dataclass
import logging
import time

from .config import LoadSheddingConfig

logger = logging.getLogger("smart_energy.load_shedding")


@dataclass(frozen=True)
class LoadSheddingDecision:
    """Bir olcumun ardindan roleye ne yapilacagi.

    `command` yalnizca gercekten bir aksiyon alinacaksa doludur; aksi halde
    None'dir ve cagiran taraf seri porta hicbir sey gondermez.
    """

    action: str  # "SHED" | "RESTORE" | "HOLD"
    reason: str
    shed_active: bool
    command: str | None = None
    power_kw: float = 0.0


class LoadSheddingController:
    """Esik asildiginda yuku kesen, dustugunde geri veren karar motoru.

    Uc mekanizma birlikte calisir:

    1. **Histerezis** - kesme ve geri verme esikleri farklidir. Tek esikle
       calisan bir sistem, tuketim esigin etrafinda salinirken roleyi saniyede
       birkac kez acip kapatir (roleyi fiziksel olarak yipratir).
    2. **Dogrulama** - bir esik asiminin aksiyona donusmesi icin ust uste
       `confirm_samples` kadar olcum gerekir. Motor kalkisi gibi anlik akim
       sicramalari boylece yuku bosuna kesmez.
    3. **Asgari aksiyon araligi** - iki role komutu arasinda en az
       `min_action_interval_seconds` gecmelidir.

    Zaman kaynagi disaridan verilebilir, boylece testler beklemek zorunda kalmaz.
    """

    def __init__(self, config: LoadSheddingConfig, clock=time.monotonic):
        if config.restore_threshold_kw >= config.shed_threshold_kw:
            raise ValueError(
                "restore_threshold_kw, shed_threshold_kw degerinden kucuk olmalidir; "
                "aksi halde histerezis olusmaz ve role surekli acilip kapanir."
            )
        if config.confirm_samples < 1:
            raise ValueError("confirm_samples en az 1 olmalidir")

        self.config = config
        self._clock = clock
        self._shed_active = False
        self._above_count = 0
        self._below_count = 0
        self._last_action_at: float | None = None

    @property
    def shed_active(self) -> bool:
        return self._shed_active

    def _interval_elapsed(self) -> bool:
        if self._last_action_at is None:
            return True

        return (self._clock() - self._last_action_at) >= self.config.min_action_interval_seconds

    def _hold(self, reason: str, power_kw: float) -> LoadSheddingDecision:
        return LoadSheddingDecision(
            action="HOLD",
            reason=reason,
            shed_active=self._shed_active,
            command=None,
            power_kw=power_kw,
        )

    def evaluate(self, active_power_w: float) -> LoadSheddingDecision:
        power_kw = active_power_w / 1000.0

        if not self.config.enabled:
            return self._hold("disabled", power_kw)

        if power_kw >= self.config.shed_threshold_kw:
            self._above_count += 1
            self._below_count = 0
        elif power_kw <= self.config.restore_threshold_kw:
            self._below_count += 1
            self._above_count = 0
        else:
            # Iki esik arasindaki bolge kararsiz bolgedir: burada hicbir sayac
            # ilerlemez, mevcut durum korunur.
            self._above_count = 0
            self._below_count = 0
            return self._hold("within_hysteresis_band", power_kw)

        if not self._shed_active and self._above_count >= self.config.confirm_samples:
            if not self._interval_elapsed():
                return self._hold("min_interval_not_elapsed", power_kw)

            self._shed_active = True
            self._above_count = 0
            self._last_action_at = self._clock()
            logger.warning(
                f"Load shedding engaged at {power_kw:.2f} kW "
                f"(threshold {self.config.shed_threshold_kw} kW)"
            )
            return LoadSheddingDecision(
                action="SHED",
                reason="threshold_exceeded",
                shed_active=True,
                command=self.config.shed_command,
                power_kw=power_kw,
            )

        if self._shed_active and self._below_count >= self.config.confirm_samples:
            if not self._interval_elapsed():
                return self._hold("min_interval_not_elapsed", power_kw)

            self._shed_active = False
            self._below_count = 0
            self._last_action_at = self._clock()
            logger.info(
                f"Load restored at {power_kw:.2f} kW "
                f"(restore threshold {self.config.restore_threshold_kw} kW)"
            )
            return LoadSheddingDecision(
                action="RESTORE",
                reason="below_restore_threshold",
                shed_active=False,
                command=self.config.restore_command,
                power_kw=power_kw,
            )

        return self._hold("awaiting_confirmation", power_kw)
