from typing import List
from dataclasses import dataclass

from syscore.exceptions import missingData

from sysdata.config.instruments import (
    get_list_of_bad_instruments_in_config,
    get_duplicate_list_of_instruments_to_remove_from_config,
    get_list_of_untradeable_instruments_in_config,
    get_list_of_ignored_instruments_in_config,
)
from sysdata.mongodb.mongo_lock_data import mongoLockData
from sysdata.mongodb.mongo_position_limits import mongoPositionLimitData
from sysdata.mongodb.mongo_trade_limits import mongoTradeLimitData
from sysdata.mongodb.mongo_temporary_override import mongoTemporaryOverrideData
from sysdata.mongodb.mongo_IB_client_id import mongoIbBrokerClientIdData
from sysdata.mongodb.mongo_temporary_close import mongoTemporaryCloseData
from sysdata.mongodb.mongo_override import mongoOverrideData
from sysdata.production.broker_client_id import brokerClientIdData
from sysproduction.data.config import (
    remove_stale_instruments_and_strategies_from_list_of_instrument_strategies,
    remove_stale_instruments_from_list_of_instruments,
    get_list_of_stale_strategies,
    get_list_of_stale_instruments,
)
from sysdata.production.locks import lockData
from sysdata.production.trade_limits import (
    tradeLimitData,
    tradeLimit,
    listOfTradeLimits,
)
from sysdata.production.override import overrideData
from sysdata.production.temporary_close import temporaryCloseData
from sysdata.production.temporary_override import temporaryOverrideData
from sysdata.production.position_limits import (
    positionLimitData,
    positionLimitForInstrument,
    positionLimitForStrategyInstrument,
)


from sysdata.data_blob import dataBlob

from sysexecution.trade_qty import tradeQuantity
from sysexecution.orders.broker_orders import brokerOrder
from sysexecution.orders.instrument_orders import instrumentOrder
from sysexecution.orders.list_of_orders import (
    listOfOrders,
    calculate_most_conservative_trade_from_list_of_orders_with_limits_applied,
)

from sysobjects.production.tradeable_object import (
    listOfInstrumentStrategies,
    instrumentStrategy,
)
from sysobjects.production.override import Override, override_no_trading
from sysobjects.production.position_limits import (
    positionLimitAndPosition,
)
from sysobjects.production.override import (
    NO_TRADE_OVERRIDE,
    REDUCE_ONLY_OVERRIDE,
    DEFAULT_OVERRIDE,
)

from sysproduction.data.positions import diagPositions
from sysproduction.data.generic_production_data import productionDataLayerGeneric

OVERRIDE_FOR_BAD = REDUCE_ONLY_OVERRIDE
OVERRIDE_FOR_BAD = REDUCE_ONLY_OVERRIDE
OVERRIDE_FOR_UNTRADEABLE = NO_TRADE_OVERRIDE
OVERRIDE_FOR_IGNORED = REDUCE_ONLY_OVERRIDE
OVERRIDE_FOR_DUPLICATE = REDUCE_ONLY_OVERRIDE


@dataclass()
class OverrideWithReason:
    override: Override
    reason: str

    def __repr__(self):
        return "%s because %s" % (str(self.override), self.reason)


class dataBrokerClientIDs(productionDataLayerGeneric):
    def _add_required_classes_to_data(self, data) -> dataBlob:
        data.add_class_object(mongoIbBrokerClientIdData)

        return data

    @property
    def db_broker_client_id_data(self) -> brokerClientIdData:
        return self.data.db_ib_broker_client_id

    def clear_all_clientids(self):
        self.db_broker_client_id_data.clear_all_clientids()


class dataLocks(productionDataLayerGeneric):
    def _add_required_classes_to_data(self, data) -> dataBlob:
        data.add_class_object(mongoLockData)

        return data

    @property
    def db_lock_data(self) -> lockData:
        return self.data.db_lock

    def is_instrument_locked(self, instrument_code: str) -> bool:
        is_it_locked = self.db_lock_data.is_instrument_locked(instrument_code)
        return is_it_locked

    def add_lock_for_instrument(self, instrument_code: str):
        self.db_lock_data.add_lock_for_instrument(instrument_code)

    def remove_lock_for_instrument(self, instrument_code: str):
        self.db_lock_data.remove_lock_for_instrument(instrument_code)

    def get_list_of_locked_instruments(self) -> list:
        return self.db_lock_data.get_list_of_locked_instruments()


class dataTradeLimits(productionDataLayerGeneric):
    def _add_required_classes_to_data(self, data) -> dataBlob:
        data.add_class_object(mongoTradeLimitData)
        return data

    @property
    def db_trade_limit_data(self) -> tradeLimitData:
        return self.data.db_trade_limit

    def what_trade_is_possible_for_strategy_instrument(
        self, instrument_strategy: instrumentStrategy, proposed_trade: tradeQuantity
    ) -> int:

        proposed_trade_qty = proposed_trade.total_abs_qty()
        possible_trade = self.what_trade_qty_possible_for_instrument_strategy(
            instrument_strategy=instrument_strategy,
            proposed_trade_qty=proposed_trade_qty,
        )

        return possible_trade

    def what_trade_qty_possible_for_instrument_strategy(
        self, instrument_strategy: instrumentStrategy, proposed_trade_qty: int
    ) -> int:

        possible_trade = (
            self.db_trade_limit_data.what_trade_is_possible_for_instrument_strategy(
                instrument_strategy, proposed_trade_qty
            )
        )

        return possible_trade

    def what_trade_qty_possible_for_instrument_code(
        self, instrument_code, proposed_trade_qty: int
    ) -> int:

        possible_trade = self.db_trade_limit_data.what_trade_is_possible_for_instrument(
            instrument_code=instrument_code, proposed_trade=proposed_trade_qty
        )

        return possible_trade

    def add_trade(self, executed_order: brokerOrder):
        trade_size = executed_order.trade.total_abs_qty()
        instrument_strategy = executed_order.instrument_strategy

        self.db_trade_limit_data.add_trade(instrument_strategy, trade_size)

    def remove_trade(self, order: brokerOrder):
        instrument_strategy = order.instrument_strategy
        trade = order.trade.total_abs_qty()

        self.db_trade_limit_data.remove_trade(instrument_strategy, trade)

    def get_all_limits_sorted(self) -> list:
        all_limits = self.get_all_limits()
        all_limits_and_codes = [
            ("%s %d" % (str(limit.instrument_strategy), limit.period_days), limit)
            for limit in all_limits
        ]
        all_limits_and_codes = sorted(all_limits_and_codes, key=lambda x: x[0])
        all_limits_sorted = [
            limit_and_code[1] for limit_and_code in all_limits_and_codes
        ]

        return all_limits_sorted

    def get_all_limits(self) -> listOfTradeLimits:
        all_limits = self.db_trade_limit_data.get_all_limits()
        all_limits = remove_stale_instruments_and_strategies_from_list_of_trade_limits(
            all_limits
        )
        return all_limits

    def update_instrument_limit_with_new_limit(
        self, instrument_code: str, period_days: int, new_limit: int
    ):
        self.db_trade_limit_data.update_instrument_limit_with_new_limit(
            instrument_code, period_days, new_limit
        )

    def reset_all_limits(self):
        self.db_trade_limit_data.reset_all_limits()

    def reset_instrument_limit(self, instrument_code: str, period_days: int):
        self.db_trade_limit_data.reset_instrument_limit(instrument_code, period_days)

    def update_instrument_strategy_limit_with_new_limit(
        self, instrument_strategy: instrumentStrategy, period_days: int, new_limit: int
    ):
        self.db_trade_limit_data.update_instrument_strategy_limit_with_new_limit(
            instrument_strategy, period_days, new_limit
        )

    def reset_instrument_strategy_limit(
        self, instrument_strategy: instrumentStrategy, period_days: int
    ):
        self.db_trade_limit_data.reset_instrument_strategy_limit(
            instrument_strategy, period_days
        )


OVERRIDE_REASON_IN_DATABASE = "in database"


class diagOverrides(productionDataLayerGeneric):
    def _add_required_classes_to_data(self, data) -> dataBlob:
        data.add_class_object(mongoOverrideData)
        return data

    @property
    def db_override_data(self) -> overrideData:
        return self.data.db_override

    def get_dict_of_all_overrides_with_reasons(self) -> dict:
        all_overrides_in_db_with_reason = (
            self.get_dict_of_all_overrides_in_db_with_reasons()
        )
        all_overrides_in_config = self.get_dict_of_all_overrides_in_config()
        all_overrides = {**all_overrides_in_db_with_reason, **all_overrides_in_config}
        all_overrides = remove_overrides_for_stale_instruments_from_dict_of_overrides(
            all_overrides
        )

        return all_overrides

    def get_dict_of_all_overrides_in_db_with_reasons(self) -> dict:
        all_overrides_in_db = self.db_override_data.get_dict_of_all_overrides()
        all_overrides_in_db_with_reason = dict(
            [
                (key, OverrideWithReason(override, OVERRIDE_REASON_IN_DATABASE))
                for key, override in all_overrides_in_db.items()
            ]
        )

        all_overrides_in_db_with_reason = (
            remove_overrides_for_stale_instruments_from_dict_of_overrides(
                all_overrides_in_db_with_reason
            )
        )

        return all_overrides_in_db_with_reason

    def get_cumulative_override_for_instrument_strategy(
        self, instrument_strategy: instrumentStrategy
    ) -> Override:

        cumulative_override_from_db = (
            self.get_cumulative_override_for_instrument_strategy_from_db(
                instrument_strategy
            )
        )
        cumulative_override_from_config = (
            self.get_cumulative_override_from_configuration(instrument_strategy)
        )
        joint_override = cumulative_override_from_db * cumulative_override_from_config

        return joint_override

    def get_cumulative_override_for_instrument_strategy_from_db(
        self, instrument_strategy: instrumentStrategy
    ) -> Override:
        cumulative_override = (
            self.db_override_data.get_cumulative_override_for_instrument_strategy(
                instrument_strategy
            )
        )

        return cumulative_override

    def get_cumulative_override_from_configuration(
        self, instrument_strategy: instrumentStrategy
    ) -> Override:
        ## will look to private_config and defaults.yaml; *NOT* backtest .yaml files
        instrument_code = instrument_strategy.instrument_code
        bad_instrument_override = self.bad_instrument_override(instrument_code)
        duplicate_instrument_override = self.duplicate_instrument_override(
            instrument_code
        )
        ignored_instrument_override = self.ignored_instrument_override(instrument_code)
        untradeable_instrument_override = self.untradeable_instrument_override(
            instrument_code
        )

        joint_override = (
            bad_instrument_override
            * duplicate_instrument_override
            * ignored_instrument_override
            * untradeable_instrument_override
        )

        return joint_override

    def bad_instrument_override(self, instrument_code: str) -> Override:
        if instrument_code in self.get_list_of_bad_instruments_in_config():
            return OVERRIDE_FOR_BAD
        else:
            return DEFAULT_OVERRIDE

    def duplicate_instrument_override(self, instrument_code: str) -> Override:
        if (
            instrument_code
            in self.get_duplicate_list_of_instruments_to_remove_from_config()
        ):
            return OVERRIDE_FOR_DUPLICATE
        else:
            return DEFAULT_OVERRIDE

    def ignored_instrument_override(self, instrument_code: str) -> Override:
        if instrument_code in self.get_list_of_ignored_instruments_in_config():
            return OVERRIDE_FOR_IGNORED
        else:
            return DEFAULT_OVERRIDE

    def untradeable_instrument_override(self, instrument_code: str) -> Override:
        if instrument_code in self.get_list_of_untradeable_instruments_in_config():
            return OVERRIDE_FOR_UNTRADEABLE
        else:
            return DEFAULT_OVERRIDE

    def get_dict_of_all_overrides_in_config(self) -> dict:
        dict_of_bad_instrument_overrides = self.get_dict_of_bad_instrument_overrides()
        dict_of_duplicate_instrument_overrides = (
            self.get_dict_of_duplicate_instrument_overrides()
        )
        dict_of_ignored_instrument_overrides = (
            self.get_dict_of_ignored_instrument_overrides()
        )
        dict_of_untradeable_instrument_overrides = (
            self.get_dict_of_untradeable_instrument_overrides()
        )

        return {
            **dict_of_ignored_instrument_overrides,
            **dict_of_untradeable_instrument_overrides,
            **dict_of_bad_instrument_overrides,
            **dict_of_duplicate_instrument_overrides,
        }

    def get_dict_of_duplicate_instrument_overrides(self):
        list_of_instruments = (
            self.get_duplicate_list_of_instruments_to_remove_from_config()
        )
        return dict(
            [
                (
                    instrument_code,
                    OverrideWithReason(
                        OVERRIDE_FOR_DUPLICATE, "duplicate_instrument in config"
                    ),
                )
                for instrument_code in list_of_instruments
            ]
        )

    def get_dict_of_bad_instrument_overrides(self):
        list_of_instruments = self.get_list_of_bad_instruments_in_config()
        return dict(
            [
                (
                    instrument_code,
                    OverrideWithReason(OVERRIDE_FOR_BAD, "bad_instrument in config"),
                )
                for instrument_code in list_of_instruments
            ]
        )

    def get_dict_of_untradeable_instrument_overrides(self):
        list_of_instruments = self.get_list_of_untradeable_instruments_in_config()
        return dict(
            [
                (
                    instrument_code,
                    OverrideWithReason(
                        OVERRIDE_FOR_UNTRADEABLE, "trading_restrictions in config"
                    ),
                )
                for instrument_code in list_of_instruments
            ]
        )

    def get_dict_of_ignored_instrument_overrides(self):
        list_of_instruments = self.get_list_of_ignored_instruments_in_config()
        return dict(
            [
                (
                    instrument_code,
                    OverrideWithReason(
                        OVERRIDE_FOR_IGNORED, "ignore_instruments in config"
                    ),
                )
                for instrument_code in list_of_instruments
            ]
        )

    def get_list_of_bad_instruments_in_config(self) -> list:
        return get_list_of_bad_instruments_in_config(self.config)

    def get_duplicate_list_of_instruments_to_remove_from_config(self) -> list:
        return get_duplicate_list_of_instruments_to_remove_from_config(self.config)

    def get_list_of_untradeable_instruments_in_config(self) -> list:
        return get_list_of_untradeable_instruments_in_config(self.config)

    def get_list_of_ignored_instruments_in_config(self) -> list:
        return get_list_of_ignored_instruments_in_config(self.config)

    @property
    def config(self):
        return self.data.config


class updateOverrides(productionDataLayerGeneric):
    def _add_required_classes_to_data(self, data: dataBlob) -> dataBlob:
        data.add_class_list([mongoOverrideData, mongoTemporaryOverrideData])
        return data

    @property
    def db_override_data(self) -> overrideData:
        return self.data.db_override

    @property
    def db_temporary_override_data(self) -> temporaryOverrideData:
        return self.data.db_temporary_override

    def update_override_for_strategy(self, strategy_name: str, new_override: Override):
        self.db_override_data.update_override_for_strategy(strategy_name, new_override)

    def update_override_for_instrument_strategy(
        self, instrument_strategy: instrumentStrategy, new_override
    ):
        self.db_override_data.update_override_for_instrument_strategy(
            instrument_strategy, new_override
        )

    def update_override_for_instrument(
        self, instrument_code: str, new_override: Override
    ):
        self.db_override_data.update_override_for_instrument(
            instrument_code, new_override
        )

    def delete_all_overrides_in_db(self, are_you_sure=False):
        self.db_override_data.delete_all_overrides(are_you_sure)

    def add_temporary_reduce_only_for_instrument(self, instrument_code):
        try:
            self.add_temporary_override_to_instrument(
                instrument_code, REDUCE_ONLY_OVERRIDE
            )
        except:
            msg = "Couldn't add reduce only temporarily for instrument as already has temporary override on"
            self.log.error(msg)
            raise Exception(msg)

    def add_temporary_override_to_instrument(
        self, instrument_code: str, temporary_override: Override
    ):
        original_override = self.db_override_data.get_override_for_instrument(
            instrument_code
        )
        self.db_temporary_override_data.add_stored_override(
            instrument_code=instrument_code, override_for_instrument=original_override
        )
        self.db_override_data.update_override_for_instrument(
            instrument_code, temporary_override
        )

        self.log.debug(
            "Temporarily setting override for %s, was %s, now %s"
            % (instrument_code, str(original_override), str(temporary_override))
        )

    def remove_temporary_override_for_instrument(self, instrument_code: str):
        stored_override = (
            self.db_temporary_override_data.get_stored_override_for_instrument(
                instrument_code
            )
        )
        temporary_override = self.db_override_data.get_override_for_instrument(
            instrument_code
        )
        self.db_override_data.update_override_for_instrument(
            instrument_code, stored_override
        )
        self.db_temporary_override_data.clear_stored_override_for_instrument(
            instrument_code
        )
        self.log.debug(
            "Removed temporary override for %s, was %s, now back to %s"
            % (instrument_code, str(temporary_override), str(stored_override))
        )


class dataPositionLimits(productionDataLayerGeneric):
    def _add_required_classes_to_data(self, data: dataBlob) -> dataBlob:
        data.add_class_list([mongoPositionLimitData, mongoTemporaryCloseData])
        return data

    @property
    def db_position_limit_data(self) -> positionLimitData:
        return self.data.db_position_limit

    @property
    def db_temporary_close_data(self) -> temporaryCloseData:
        return self.data.db_temporary_close

    def apply_position_limit_to_order(self, order: instrumentOrder) -> instrumentOrder:

        list_of_orders = self._get_list_of_orders_after_position_limits_applied(order)

        ## use instrument position as it includes everything
        instrument_strategy = order.instrument_strategy
        instrument_code = instrument_strategy.instrument_code
        position = self._get_current_position_for_instrument(instrument_code)

        new_order = (
            calculate_most_conservative_trade_from_list_of_orders_with_limits_applied(
                position=position, original_order=order, list_of_orders=list_of_orders
            )
        )

        return new_order

    def _get_list_of_orders_after_position_limits_applied(
        self, order: instrumentOrder
    ) -> listOfOrders:

        instrument_strategy = order.instrument_strategy
        instrument_code = instrument_strategy.instrument_code

        order_with_instrument_strategy_limit_applied = (
            self._apply_instrument_strategy_position_limit_to_order(
                instrument_strategy, order
            )
        )
        order_with_instrument_limit_applied = (
            self._apply_instrument_position_limit_to_order(instrument_code, order)
        )

        list_of_orders = listOfOrders(
            [
                order_with_instrument_limit_applied,
                order_with_instrument_strategy_limit_applied,
            ]
        )

        return list_of_orders

    def _apply_instrument_strategy_position_limit_to_order(
        self, instrument_strategy: instrumentStrategy, order: instrumentOrder
    ) -> instrumentOrder:

        position_and_limit = self._get_limit_and_position_for_instrument_strategy(
            instrument_strategy
        )
        order_with_instrument_strategy_limit_applied = (
            position_and_limit.apply_position_limit_to_order(order)
        )

        # Ignore warning instrumentOrder inherits from Order
        return order_with_instrument_strategy_limit_applied

    def get_maximum_position_contracts_for_instrument_strategy(
        self, instrument_strategy: instrumentStrategy
    ) -> int:

        ## FIXME: THIS WON'T WORK IF THERE ARE MULTIPLE STRATEGIES TRADING AN INSTRUMENT

        limit_for_instrument = self._get_position_limit_object_for_instrument(
            instrument_strategy.instrument_code
        )

        limit_for_instrument_strategy = (
            self._get_position_limit_object_for_instrument_strategy(instrument_strategy)
        )

        minimum_limit_contracts = limit_for_instrument.minimum_position_limit(
            limit_for_instrument_strategy
        )

        return minimum_limit_contracts

    def _get_limit_and_position_for_instrument_strategy(
        self, instrument_strategy: instrumentStrategy
    ) -> positionLimitAndPosition:
        limit_object = self._get_position_limit_object_for_instrument_strategy(
            instrument_strategy
        )
        position = self._get_current_position_for_instrument_strategy(
            instrument_strategy
        )

        position_and_limit = positionLimitAndPosition(limit_object, position)

        return position_and_limit

    def _get_position_limit_object_for_instrument_strategy(
        self, instrument_strategy: instrumentStrategy
    ) -> positionLimitForStrategyInstrument:
        limit_object = self.db_position_limit_data.get_position_limit_object_for_instrument_strategy(
            instrument_strategy
        )
        return limit_object

    def _get_current_position_for_instrument_strategy(
        self, instrument_strategy: instrumentStrategy
    ) -> int:
        diag_positions = diagPositions(self.data)
        position = diag_positions.get_current_position_for_instrument_strategy(
            instrument_strategy
        )

        return position

    def _apply_instrument_position_limit_to_order(
        self, instrument_code: str, order: instrumentOrder
    ) -> instrumentOrder:

        position_and_limit = self._get_limit_and_position_for_instrument(
            instrument_code
        )
        order_with_instrument_limit_applied = (
            position_and_limit.apply_position_limit_to_order(order)
        )

        # Ignore warning instrumentOrder inherits from Order
        return order_with_instrument_limit_applied

    def _get_limit_and_position_for_instrument(
        self, instrument_code: str
    ) -> positionLimitAndPosition:
        limit_object = self._get_position_limit_object_for_instrument(instrument_code)
        position = self._get_current_position_for_instrument(instrument_code)

        position_and_limit = positionLimitAndPosition(limit_object, position)

        return position_and_limit

    def _get_position_limit_object_for_instrument(
        self, instrument_code
    ) -> positionLimitForInstrument:
        limit_object = (
            self.db_position_limit_data.get_position_limit_object_for_instrument(
                instrument_code
            )
        )

        return limit_object

    def _get_current_position_for_instrument(self, instrument_code: str) -> int:
        diag_positions = diagPositions(self.data)
        position = diag_positions.get_current_instrument_position_across_strategies(
            instrument_code
        )

        return position

    ## Get all limits

    def get_all_instrument_limits_and_positions(self) -> list:
        instrument_list = self._get_all_relevant_instruments()
        list_of_limit_and_position = [
            self._get_limit_and_position_for_instrument(instrument_code)
            for instrument_code in instrument_list
        ]

        return list_of_limit_and_position

    def _get_all_relevant_instruments(self):
        ## want limits both for the union of instruments where we have positions & limits are set
        instrument_list_held = self._get_instruments_with_current_positions()
        instrument_list_limits = self._get_instruments_with_position_limits()

        instrument_list = list(set(instrument_list_held + instrument_list_limits))

        instrument_list = remove_stale_instruments_from_list_of_instruments(
            instrument_list
        )

        return instrument_list

    def _get_instruments_with_current_positions(self) -> list:
        diag_positions = diagPositions(self.data)
        instrument_list = (
            diag_positions.get_list_of_instruments_with_current_positions()
        )

        return instrument_list

    def _get_instruments_with_position_limits(self) -> list:
        instrument_list = self.db_position_limit_data.get_all_instruments_with_limits()

        return instrument_list

    def get_all_strategy_instrument_limits_and_positions(self) -> list:
        instrument_strategy_list = self._get_all_relevant_strategy_instruments()
        list_of_limit_and_position = [
            self._get_limit_and_position_for_instrument_strategy(instrument_strategy)
            for instrument_strategy in instrument_strategy_list
        ]

        return list_of_limit_and_position

    def _get_all_relevant_strategy_instruments(self) -> listOfInstrumentStrategies:
        ## want limits both for the union of strategy/instruments where we have positions & limits are set
        # return list of tuple strategy_name, instrument_code
        strategy_instrument_list_held = (
            self._get_instrument_strategies_with_current_positions()
        )
        strategy_instrument_list_limits = (
            self._get_strategy_instruments_with_position_limits()
        )

        strategy_instrument_list = (
            strategy_instrument_list_held.unique_join_with_other_list(
                strategy_instrument_list_limits
            )
        )

        return strategy_instrument_list

    def _get_instrument_strategies_with_current_positions(
        self,
    ) -> listOfInstrumentStrategies:
        diag_positions = diagPositions(self.data)
        strategy_instrument_list_held = (
            diag_positions.get_list_of_strategies_and_instruments_with_positions()
        )

        return strategy_instrument_list_held

    def _get_strategy_instruments_with_position_limits(
        self,
    ) -> listOfInstrumentStrategies:
        # return list of tuple strategy_name, instrument_code
        strategy_instrument_list_limits = (
            self.db_position_limit_data.get_all_instrument_strategies_with_limits()
        )
        strategy_instrument_list_limits_with_stale_removed = (
            remove_stale_instruments_and_strategies_from_list_of_instrument_strategies(
                strategy_instrument_list_limits
            )
        )

        return strategy_instrument_list_limits_with_stale_removed

    def temporarily_set_position_limit_to_zero_and_store_original_limit(
        self, instrument_code
    ):
        original_limit = self._get_position_limit_object_for_instrument(instrument_code)
        self.db_temporary_close_data.add_stored_position_limit(original_limit)
        self.set_abs_position_limit_for_instrument(instrument_code, 0)

        self.log.debug(
            "Temporarily setting position limit, was %s, now zero"
            % (str(original_limit))
        )

    def reset_position_limit_for_instrument_to_original_value(self, instrument_code):
        try:
            original_limit = (
                self.db_temporary_close_data.get_stored_position_limit_for_instrument(
                    instrument_code
                )
            )
        except missingData:
            self.log.warning("No temporary position limit stored")
            return None

        self.set_abs_position_limit_for_instrument(
            instrument_code, original_limit.position_limit
        )

        self.db_temporary_close_data.clear_stored_position_limit_for_instrument(
            instrument_code
        )
        self.log.debug(
            "Reset position limit from temporary zero limit, now %s"
            % str(original_limit)
        )

    ## set limits

    def set_position_limit_for_instrument_strategy(
        self, instrument_strategy: instrumentStrategy, new_position_limit: int
    ):

        self.db_position_limit_data.set_position_limit_for_instrument_strategy(
            instrument_strategy, new_position_limit
        )

    def set_abs_position_limit_for_instrument(
        self, instrument_code: str, new_position_limit: int
    ):

        self.db_position_limit_data.set_position_limit_for_instrument(
            instrument_code, new_position_limit
        )

    def delete_position_limit_for_instrument_strategy(
        self, instrument_strategy: instrumentStrategy
    ):

        self.db_position_limit_data.delete_position_limit_for_instrument_strategy(
            instrument_strategy
        )

    def delete_position_limit_for_instrument(self, instrument_code: str):

        self.db_position_limit_data.delete_position_limit_for_instrument(
            instrument_code
        )


def remove_stale_instruments_and_strategies_from_list_of_trade_limits(
    all_limits: listOfTradeLimits,
) -> listOfTradeLimits:
    filtered_list = remove_stale_instruments_from_list_of_trade_limits(all_limits)
    twice_filtered_list = remove_stale_strategies_from_list_of_trade_limits(
        filtered_list
    )

    return twice_filtered_list


def remove_stale_instruments_from_list_of_trade_limits(
    all_limits: listOfTradeLimits,
) -> listOfTradeLimits:
    list_of_stale_instruments = get_list_of_stale_instruments()
    filtered_list = all_limits.filter_to_remove_list_of_instruments(
        list_of_stale_instruments
    )

    return filtered_list


def remove_stale_strategies_from_list_of_trade_limits(
    all_limits: listOfTradeLimits,
) -> listOfTradeLimits:
    list_of_stale_strategies = get_list_of_stale_strategies()
    filtered_list = all_limits.filter_to_remove_list_of_strategy_names(
        list_of_stale_strategies
    )

    return filtered_list


def remove_overrides_for_stale_instruments_from_dict_of_overrides(
    dict_of_overrides: dict,
) -> dict:
    list_of_stale_instruments = get_list_of_stale_instruments()
    filtered_dict = dict(
        [
            (key, value)
            for key, value in dict_of_overrides.items()
            if key not in list_of_stale_instruments
        ]
    )

    return filtered_dict
