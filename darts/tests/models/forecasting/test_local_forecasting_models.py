import os
import shutil
import tempfile

import numpy as np
import pandas as pd

from darts.datasets import AirPassengersDataset, IceCreamHeaterDataset
from darts.logging import get_logger
from darts.metrics import mape
from darts.models import (
    ARIMA,
    BATS,
    FFT,
    TBATS,
    VARIMA,
    AutoARIMA,
    Croston,
    ExponentialSmoothing,
    FourTheta,
    KalmanForecaster,
    LinearRegressionModel,
    NaiveSeasonal,
    Prophet,
    RandomForest,
    StatsForecastAutoARIMA,
    Theta,
)
from darts.models.forecasting.forecasting_model import (
    TransferableDualCovariatesForecastingModel,
)
from darts.tests.base_test_class import DartsBaseTestClass
from darts.timeseries import TimeSeries
from darts.utils import timeseries_generation as tg
from darts.utils.utils import ModelMode, SeasonalityMode, TrendMode

logger = get_logger(__name__)

# (forecasting models, maximum error) tuples
models = [
    (ExponentialSmoothing(), 5.6),
    (ARIMA(12, 2, 1), 10),
    (ARIMA(1, 1, 1), 40),
    (StatsForecastAutoARIMA(period=12), 4.8),
    (Croston(version="classic"), 34),
    (Croston(version="tsb", alpha_d=0.1, alpha_p=0.1), 34),
    (Theta(), 11.3),
    (Theta(1), 20.2),
    (Theta(-1), 9.8),
    (FourTheta(1), 20.2),
    (FourTheta(-1), 9.8),
    (FourTheta(trend_mode=TrendMode.EXPONENTIAL), 5.5),
    (FourTheta(model_mode=ModelMode.MULTIPLICATIVE), 11.4),
    (FourTheta(season_mode=SeasonalityMode.ADDITIVE), 14.2),
    (FFT(trend="poly"), 11.4),
    (NaiveSeasonal(), 32.4),
    (KalmanForecaster(dim_x=3), 17.0),
    (LinearRegressionModel(lags=12), 11.0),
    (RandomForest(lags=12, n_estimators=5, max_depth=3), 17.0),
]

# forecasting models with exogenous variables support
multivariate_models = [
    (VARIMA(1, 0, 0), 55.6),
    (VARIMA(1, 1, 1), 57.0),
    (KalmanForecaster(dim_x=30), 30.0),
]

dual_models = [ARIMA(), StatsForecastAutoARIMA(period=12)]


models.append((Prophet(), 13.5))
dual_models.append(Prophet())

models.append((AutoARIMA(), 12.2))
models.append((TBATS(use_trend=True, use_arma_errors=True, use_box_cox=True), 8.0))
models.append((BATS(use_trend=True, use_arma_errors=True, use_box_cox=True), 10.0))
dual_models.append(AutoARIMA())


class LocalForecastingModelsTestCase(DartsBaseTestClass):

    # forecasting horizon used in runnability tests
    forecasting_horizon = 5

    # dummy timeseries for runnability tests
    np.random.seed(1)
    ts_gaussian = tg.gaussian_timeseries(length=100, mean=50)
    # for testing covariate slicing
    ts_gaussian_long = tg.gaussian_timeseries(
        length=len(ts_gaussian) + 2 * forecasting_horizon,
        start=ts_gaussian.start_time() - forecasting_horizon * ts_gaussian.freq,
        mean=50,
    )

    # real timeseries for functionality tests
    ts_passengers = AirPassengersDataset().load()
    ts_pass_train, ts_pass_val = ts_passengers.split_after(pd.Timestamp("19570101"))

    # real multivariate timeseries for functionality tests
    ts_ice_heater = IceCreamHeaterDataset().load()
    ts_ice_heater_train, ts_ice_heater_val = ts_ice_heater.split_after(split_point=0.7)

    def setUp(self):
        self.temp_work_dir = tempfile.mkdtemp(prefix="darts")

    def tearDown(self):
        shutil.rmtree(self.temp_work_dir)

    def test_save_model_parameters(self):
        # model creation parameters were saved before. check if re-created model has same params as original
        for model, _ in models:
            self.assertTrue(
                model._model_params == model.untrained_model()._model_params
            )

    def test_save_load_model(self):
        # check if save and load methods work and if loaded model creates same forecasts as original model
        cwd = os.getcwd()
        os.chdir(self.temp_work_dir)

        for model in [ARIMA(1, 1, 1), LinearRegressionModel(lags=12)]:
            model_path = type(model).__name__
            model_path_f = model_path + "_f"

            full_model_path = os.path.join(self.temp_work_dir, model_path)
            full_model_path_f = os.path.join(self.temp_work_dir, model_path_f)
            full_model_paths = [full_model_path, full_model_path_f]

            model.fit(self.ts_gaussian)
            model_prediction = model.predict(self.forecasting_horizon)

            # test save
            model.save()
            model.save(model_path)
            with open(model_path_f, "wb") as f:
                model.save(f)

            for full_model_p in full_model_paths:
                self.assertTrue(os.path.exists(full_model_p))

            # test load
            loaded_model = type(model).load(model_path)
            loaded_model_f = type(model).load(model_path_f)
            loaded_models = [loaded_model, loaded_model_f]

            for loaded_model in loaded_models:
                self.assertEqual(
                    model_prediction, loaded_model.predict(self.forecasting_horizon)
                )

        os.chdir(cwd)

    def test_models_runnability(self):
        for model, _ in models:
            prediction = model.fit(self.ts_gaussian).predict(self.forecasting_horizon)
            self.assertTrue(len(prediction) == self.forecasting_horizon)

    def test_models_performance(self):
        # for every model, check whether its errors do not exceed the given bounds
        for model, max_mape in models:
            np.random.seed(1)  # some models are probabilist...
            model.fit(self.ts_pass_train)
            prediction = model.predict(len(self.ts_pass_val))
            current_mape = mape(prediction, self.ts_pass_val)
            self.assertTrue(
                current_mape < max_mape,
                "{} model exceeded the maximum MAPE of {}. "
                "with a MAPE of {}".format(str(model), max_mape, current_mape),
            )

    def test_multivariate_models_performance(self):
        # for every model, check whether its errors do not exceed the given bounds
        for model, max_mape in multivariate_models:
            np.random.seed(1)
            model.fit(self.ts_ice_heater_train)
            prediction = model.predict(len(self.ts_ice_heater_val))
            current_mape = mape(prediction, self.ts_ice_heater_val)
            self.assertTrue(
                current_mape < max_mape,
                "{} model exceeded the maximum MAPE of {}. "
                "with a MAPE of {}".format(str(model), max_mape, current_mape),
            )

    def test_multivariate_input(self):
        es_model = ExponentialSmoothing()
        ts_passengers_enhanced = self.ts_passengers.add_datetime_attribute("month")
        with self.assertRaises(AssertionError):
            es_model.fit(ts_passengers_enhanced)
        es_model.fit(ts_passengers_enhanced["#Passengers"])
        with self.assertRaises(KeyError):
            es_model.fit(ts_passengers_enhanced["2"])

    def test_exogenous_variables_support(self):
        # test case with pd.DatetimeIndex
        target_dt_idx = self.ts_gaussian
        fc_dt_idx = self.ts_gaussian_long

        # test case with numerical pd.RangeIndex
        target_num_idx = TimeSeries.from_times_and_values(
            times=tg._generate_index(start=0, length=len(self.ts_gaussian)),
            values=self.ts_gaussian.all_values(copy=False),
        )
        fc_num_idx = TimeSeries.from_times_and_values(
            times=tg._generate_index(start=0, length=len(self.ts_gaussian_long)),
            values=self.ts_gaussian_long.all_values(copy=False),
        )

        for target, future_covariates in zip(
            [target_dt_idx, target_num_idx], [fc_dt_idx, fc_num_idx]
        ):
            for model in dual_models:
                # skip models which do not support RangeIndex
                if isinstance(target.time_index, pd.RangeIndex):
                    try:
                        # _supports_range_index raises a ValueError if model does not support RangeIndex
                        model._supports_range_index()
                    except ValueError:
                        continue

                # Test models runnability - proper future covariates slicing
                model.fit(target, future_covariates=future_covariates)
                prediction = model.predict(
                    self.forecasting_horizon, future_covariates=future_covariates
                )

                self.assertTrue(len(prediction) == self.forecasting_horizon)

                # Test mismatch in length between exogenous variables and forecasting horizon
                with self.assertRaises(ValueError):
                    model.predict(
                        self.forecasting_horizon,
                        future_covariates=tg.gaussian_timeseries(
                            start=future_covariates.start_time(),
                            length=self.forecasting_horizon - 1,
                        ),
                    )

                # Test mismatch in time-index/length between series and exogenous variables
                with self.assertRaises(ValueError):
                    model.fit(target, future_covariates=target[:-1])
                with self.assertRaises(ValueError):
                    model.fit(target[1:], future_covariates=target[:-1])

    def test_dummy_series(self):
        values = np.random.uniform(low=-10, high=10, size=100)
        ts = TimeSeries.from_dataframe(pd.DataFrame({"V1": values}))

        varima = VARIMA(trend="t")
        with self.assertRaises(ValueError):
            varima.fit(series=ts)

        autoarima = AutoARIMA(trend="t")
        with self.assertRaises(ValueError):
            autoarima.fit(series=ts)

    def test_statsmodels_dual_models(self):

        # same tests, but VARIMA requires to work on a multivariate target series
        UNIVARIATE = "univariate"
        MULTIVARIATE = "multivariate"

        params = [
            (ARIMA, {}, UNIVARIATE),
            (VARIMA, {"d": 0}, MULTIVARIATE),
            (VARIMA, {"d": 1}, MULTIVARIATE),
        ]

        for model_cls, kwargs, model_type in params:
            pred_len = 5
            if model_type == MULTIVARIATE:
                series1 = self.ts_ice_heater_train
                series2 = self.ts_ice_heater_val
            else:
                series1 = self.ts_pass_train
                series2 = self.ts_pass_val

            # creating covariates from series + noise
            noise1 = tg.gaussian_timeseries(length=len(series1))
            noise2 = tg.gaussian_timeseries(length=len(series2))

            for _ in range(1, series1.n_components):
                noise1 = noise1.stack(tg.gaussian_timeseries(length=len(series1)))
                noise2 = noise2.stack(tg.gaussian_timeseries(length=len(series2)))

            exog1 = series1 + noise1
            exog2 = series2 + noise2

            exog1_longer = exog1.concatenate(exog1, ignore_time_axis=True)
            exog2_longer = exog2.concatenate(exog2, ignore_time_axis=True)

            # shortening of pred_len so that exog are enough for the training series prediction
            series1 = series1[:-pred_len]
            series2 = series2[:-pred_len]

            # check runnability with different time series
            model = model_cls(**kwargs)
            model.fit(series1)
            pred1 = model.predict(n=pred_len)
            pred2 = model.predict(n=pred_len, series=series2)

            # check probabilistic forecast
            n_samples = 3
            pred1 = model.predict(n=pred_len, num_samples=n_samples)
            pred2 = model.predict(n=pred_len, series=series2, num_samples=n_samples)

            # check that the results with a second custom ts are different from the results given with the training ts
            self.assertFalse(np.array_equal(pred1.values, pred2.values()))

            # check runnability with exogeneous variables
            model = model_cls(**kwargs)
            model.fit(series1, future_covariates=exog1)
            pred1 = model.predict(n=pred_len, future_covariates=exog1)
            pred2 = model.predict(n=pred_len, series=series2, future_covariates=exog2)

            self.assertFalse(np.array_equal(pred1.values(), pred2.values()))

            # check runnability with future covariates with extra time steps in the past compared to the target series
            model = model_cls(**kwargs)
            model.fit(series1, future_covariates=exog1_longer)
            pred1 = model.predict(n=pred_len, future_covariates=exog1_longer)
            pred2 = model.predict(
                n=pred_len, series=series2, future_covariates=exog2_longer
            )

            # check error is raised if model expects covariates but those are not passed when predicting with new data
            with self.assertRaises(ValueError):
                model = model_cls(**kwargs)
                model.fit(series1, future_covariates=exog1)
                model.predict(n=pred_len, series=series2)

            # check error is raised if new future covariates are not wide enough for prediction (on the original series)
            with self.assertRaises(ValueError):
                model = model_cls(**kwargs)
                model.fit(series1, future_covariates=exog1)
                model.predict(n=pred_len, future_covariates=exog1[:-pred_len])

            # check error is raised if new future covariates are not wide enough for prediction (on a new series)
            with self.assertRaises(ValueError):
                model = model_cls(**kwargs)
                model.fit(series1, future_covariates=exog1)
                model.predict(
                    n=pred_len, series=series2, future_covariates=exog2[:-pred_len]
                )
            # and checking the case with unsufficient historic future covariates
            with self.assertRaises(ValueError):
                model = model_cls(**kwargs)
                model.fit(series1, future_covariates=exog1)
                model.predict(
                    n=pred_len, series=series2, future_covariates=exog2[pred_len:]
                )

            # verify that we can still forecast the original training series after predicting a new target series
            model = model_cls(**kwargs)
            model.fit(series1, future_covariates=exog1)
            pred1 = model.predict(n=pred_len, future_covariates=exog1)
            model.predict(n=pred_len, series=series2, future_covariates=exog2)
            pred3 = model.predict(n=pred_len, future_covariates=exog1)

            self.assertTrue(np.array_equal(pred1.values(), pred3.values()))

            # check backtesting with retrain=False
            model: TransferableDualCovariatesForecastingModel = model_cls(**kwargs)
            model.backtest(series1, future_covariates=exog1, retrain=False)
