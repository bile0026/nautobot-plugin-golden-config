"""hier_config job for generating the remediation data."""
# pylint: disable=relative-beyond-top-level
from asyncio import tasks
import difflib
import logging
import os

import hier_config

from datetime import datetime

from netutils.config.compliance import parser_map, section_config, _open_file_config
from nornir import InitNornir
from nornir.core.plugins.inventory import InventoryPluginRegister
from nornir.core.task import Result, Task

from nornir_nautobot.exceptions import NornirNautobotException
from nornir_nautobot.utils.logger import NornirLogger

from nautobot_plugin_nornir.plugins.inventory.nautobot_orm import NautobotORMInventory
from nautobot_plugin_nornir.constants import NORNIR_SETTINGS

from nautobot_golden_config.models import ComplianceRule, ConfigCompliance, GoldenConfigSetting, GoldenConfig
from nautobot_golden_config.utilities.helper import (
    get_device_to_settings_map,
    get_job_filter,
    verify_settings,
    render_jinja_template,
)
from nautobot_golden_config.nornir_plays.processor import ProcessGoldenConfig
from nautobot_golden_config.utilities.utils import get_platform

InventoryPluginRegister.register("nautobot-inventory", NautobotORMInventory)
LOGGER = logging.getLogger(__name__)

def get_rules():
  pass

def run_remediation(
  task: Task,
  logger,
  device_to_settings_map,
  rules,
) -> Result:
    """Premake data for remediation task.

    Args:
      task (Task): Hier_config task individual object

    Returns:
      result (Result): Result from hier_config tasks
    """

    obj = task.host.data["obj"]
    settings = device_to_settings_map[obj.id]

    compliance_obj = GoldenConfig.objects.filter(device=obj).first()
    if not compliance_obj:
        compliance_obj = GoldenConfig.objects.create(device=obj)
    compliance_obj.compliance_last_attempt_date = task.host.defaults.data["now"]
    compliance_obj.save()

    intended_directory = settings.intended_repository.filesystem_path
    intended_path_template_obj = render_jinja_template(obj, logger, settings.intended_path_template)
    intended_file = os.path.join(intended_directory, intended_path_template_obj)

    if not os.path.exists(intended_file):
        logger.log_failure(obj, f"Unable to locate intended file for device at {intended_file}")
        raise NornirNautobotException()

    backup_directory = settings.backup_repository.filesystem_path
    backup_template = render_jinja_template(obj, logger, settings.backup_path_template)
    backup_file = os.path.join(backup_directory, backup_template)

    if not os.path.exists(backup_file):
        logger.log_failure(obj, f"Unable to locate backup file for device at {backup_file}")
        raise NornirNautobotException()

    platform = obj.platform.slug
    if not rules.get(platform):
        logger.log_failure(obj, f"There is no defined `Configuration Rule` for platform slug `{platform}`.")
        raise NornirNautobotException()

    if get_platform(platform) not in parser_map.keys():
        logger.log_failure(obj, f"There is currently no parser support for platform slug `{get_platform(platform)}`.")
        raise NornirNautobotException()

    backup_cfg = _open_file_config(backup_file)
    intended_cfg = _open_file_config(intended_file)