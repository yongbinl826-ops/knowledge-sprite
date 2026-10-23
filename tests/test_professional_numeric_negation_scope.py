"""Observed correct negative claims and unrelated-negation controls."""
import pytest
from backend.app.project_analysis import _asserts_wrong_uno_resolution

@pytest.mark.parametrize("text", [
    "PWM与ADC并非均为10位。",
    "PWM与ADC不是都为10位。",
    "PWM与ADC的位宽并不都为10位。",
    "PWM与ADC均不为10位。",
    "PWM与ADC都不是10位。",
    "PWM与ADC并非均为8位。",
    "PWM and ADC are not both 10-bit.",
])
def test_negative_shared_width_claim_is_not_an_affirmative_contradiction(text):
    assert not _asserts_wrong_uno_resolution(text)

@pytest.mark.parametrize("text", [
    "Uno的PWM与ADC均为板载10位。",
    "PWM与ADC都为8位。",
    "不使用ESP32但PWM与ADC均为10位。",
    "不能默认为ESP32但是Uno的PWM与ADC均为10位。",
    "不要用其他板，不过Uno的PWM与ADC均为10位。",
    "Do not use ESP32 but Uno PWM and ADC are both 10-bit.",
])
def test_unrelated_negative_instruction_does_not_excuse_positive_wrong_claim(text):
    assert _asserts_wrong_uno_resolution(text)
