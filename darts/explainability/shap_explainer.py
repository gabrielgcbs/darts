"""
Shap Explainability wrapper Class
------------------------------
"""

from darts.explainability.explainability import ForecastingModelExplainer
from darts.models.forecasting.forecasting_model import (
    ForecastingModel,
    GlobalForecastingModel,
)
from darts.models.forecasting.regression_model import RegressionModel
from darts.utils import retain_period_common_to_all
from darts import TimeSeries
from darts.logging import get_logger, raise_log, raise_if

import matplotlib.pyplot as plt

from typing import Optional, Union, Sequence

import pandas as pd

import shap

from sklearn.multioutput import MultiOutputRegressor


logger = get_logger(__name__)


class ShapExplainer(ForecastingModelExplainer):
    def __init__(
        self,
        model: ForecastingModel,
        background_series: Optional[Union[TimeSeries, Sequence[TimeSeries]]] = None,
        background_past_covariates: Optional[
            Union[TimeSeries, Sequence[TimeSeries]]
        ] = None,
        background_future_covariates: Optional[
            Union[TimeSeries, Sequence[TimeSeries]]
        ] = None,
    ):

        """Shap-based ForecastingModelExplainer

        This class is meant to wrap a shap explainer (https://github.com/slundberg/shap) specifically for time series.

        A time series prediction model is a machine learning/statistic model with features being the past targets ts,
        past covariates ts and future covariates ts, at different lags.
        Hence we can explain the predictions with shap values for each lag and ts.

        Warning

        This is only a shap value of direct influence and doesn't take into account relationships
        between past lags themselves. Hence a given past lag could also have an indirect influence via the
        intermediate past lags elements between it and the time step we want to explain, if we assume that
        the intermediate past lags are generated by the same model.

        Parameters
        ----------
        model
            A ForecastingModel we want to explain. It has to be fitted first.

        background_series
            A TimeSeries or a list of time series we want to use to compare with any foreground we want to explain.
            This is optional, for 2 reasons:
                - In general we want to keep the training_series of the model and this is the default one,
                but in case of multiple time series training (global or meta learning) the ForecastingModel doesn't
                save them. In this case we need to feed a background time series.
                - We might want to consider a reduced well chosen background in order to reduce computation
                time.
        background_past_covariates
            A past covariates TimeSeries or list of TimeSeries that the model needs once fitted.
        background_future_covariates
            A future covariates TimeSeries or list of TimeSeries that the model needs once fitted.
        n
            Optionally, Number of predictions ahead we want to explain. It will provide complete explanation for each
            future n steps.
            If we have existence of output_chunk_length, then n := output_chunk_length automatically.
            (TODO Not sure it is really needed. Indeed, if there is no output_chunk_length, would be just n=1
            enough? The only question is do we want to explain at any time step in the future with
            autoregressive models. Also, we could explain further than output_chunk_length)
        past_steps_explain
            A number of timesteps in the past of which we want to estimate the shap values. If x_t is
            our prediction, past_steps_explain = p will take (t-1) ... (t-p) features in the past
            (past target, past covariates, future covariates).
            If we have existence of input_chunk_length (for regression models, the farthest past lag gives the length),
            then past_steps_explain := input_chunk_length.

        TODO
            Optional De-trend  if the timeseries is not stationary.
            There would be 1) a stationarity test and 2) a de-trend methodology for the target. It can be for
            example target - moving_average(input_chunk_length).

        """

        if not issubclass(type(model), RegressionModel):
            raise_log(
                ValueError(
                    "Invalid model type. For now, only RegressionModel type can be explained."
                ),
                logger,
            )

        super().__init__(
            model,
            background_series,
            background_past_covariates,
            background_future_covariates,
        )

        self.explainers = RegressionShapExplainers(
            self.model,
            self.background_series,
            self.background_past_covariates,
            self.background_future_covariates,
        )

    def explain_from_input(
        self,
        foreground_series: TimeSeries,
        foreground_past_covariates: Optional[TimeSeries],
        foreground_future_covariates: Optional[TimeSeries],
        horizons: Optional[Sequence[int]] = None,
        target_names: Optional[Sequence[str]] = None,
    ) -> Sequence[Sequence[TimeSeries]]:

        shap_values_dict = self.shap_values(
            foreground_series,
            foreground_past_covariates,
            foreground_future_covariates,
            horizons,
            target_names,
        )

        if target_names is None:
            target_names = self.target_names
        if horizons is None:
            horizons = range(self.n)

        for h in horizons:
            for t in target_names:
                shap_values_dict[h][t] = TimeSeries.from_times_and_values(
                    shap_values_dict[h][t].time_index,
                    shap_values_dict[h][t].values,
                    columns=shap_values_dict[h][t].feature_names,
                )

        return shap_values_dict

    def shap_values(
        self,
        foreground_series: TimeSeries,
        foreground_past_covariates: Optional[TimeSeries],
        foreground_future_covariates: Optional[TimeSeries],
        horizons: Optional[Sequence[int]] = None,
        target_names: Optional[Sequence[str]] = None,
    ) -> Sequence[Sequence[shap._explanation.Explanation]]:
        """
        Return shap values Explanation objects for a given foreground TimeSeries.

        Parameters
        ----------
        foreground_series
            TimeSeries target we want to explain. Can be multivariate.
        foreground_past_covariates
            Optionally, past covariate timeseries if needed by model.
        foreground_future_covariates
            Optionally, future covariate timeseries if needed by model.
        horizons
            Optionally, a list of integer values representing which elements in the future
            we want to explain, starting from the first timestamp prediction at 0.
            For now we consider only models with output_chunk_length and it can't be bigger than
            output_chunk_length.
            If no input, then all elements of output_chunk_length will be explained.
        target_names
            Optionally, a list of string values naming the targets we want to explain.
            If no input, then all targets will be explained.

        Returns
        -------
        a shap Explanation dictionary of dictionaries of shap Explanation objects:
            - each element of the first dictionary is corresponding to an horizon
            - each element of the second layer dictionary is corresponding to a target
        """

        shap_values_dict = {}
        if target_names is None:
            target_names = self.target_names
        if horizons is None:
            horizons = range(self.n)

        for h in horizons:
            dict_h = {}
            for t in target_names:
                dict_h[t] = self.explainers.shap_values(
                    foreground_series,
                    foreground_past_covariates,
                    foreground_future_covariates,
                    h,
                    t,
                )
            shap_values_dict[h] = dict_h

        return shap_values_dict

    def summary_plot(
        self,
        target_names: Optional[Sequence[str]] = None,
        horizons: Optional[Sequence[int]] = None,
        nb_samples: Optional[int] = None,
        plot_type: Optional[str] = "dot",
    ):
        """
        Dispay a shap plot summary per target and per horizon.
        We here reuse the background data as foreground (potentially sampled) to give a general importance
        plot for each feature.
        If no target names and/or no horizons are provided, we plot all summary plots in the non specified
        dimension (target_names or horizons).

        Parameters
        ----------
        target_names
            Optionally, A list of string naming the target names we want to plot.
        horizons
            Optionally, a list of integer values representing which elements in the future
            we want to explain, starting from the first timestamp prediction at 0.
            For now we consider only models with output_chunk_length and it can't be bigger than output_chunk_length.
        nb_samples
            Optionally, an integer value sampling the foreground series (based on the backgound),
            for the sake of performance.
        plot_type
            Optionally, string value for the type of plot proposed by shap library. Currently,
            the following are available: 'dot', 'bar', 'violin'.

        """

        if target_names is not None:
            raise_if(
                any(
                    [
                        target_name not in self.target_names
                        for target_name in target_names
                    ]
                ),
                "One of the target names doesn't exist in the original background ts.",
            )

        if horizons is not None:
            # We suppose for now the output_chunk_length existence
            raise_if(
                max(horizons) > self.n - 1,
                "One of the horizons is greater than the model output_chunk_length.",
            )

        if nb_samples:
            foreground_X_sampled = shap.utils.sample(
                self.explainers.background_X, nb_samples
            )
        else:
            foreground_X_sampled = self.explainers.background_X

        shap_values = []
        if target_names is None:
            target_names = self.target_names
        if horizons is None:
            horizons = range(self.model.output_chunk_length)

        for t in target_names:
            for h in horizons:
                shap_values.append(
                    self.explainers.shap_values_from_X(foreground_X_sampled, h, t)
                )
                plt.title("Target: `{}` - Horizon: {}".format(t, "t+" + str(h)))
                shap.summary_plot(
                    shap_values[-1], foreground_X_sampled, plot_type=plot_type
                )


class RegressionShapExplainers:
    """
    Helper Class to wrap the different cases we encounter with shap different explainers, multivariates,
    horizon etc.
    Aim to provide shap values for any type of RegressionModel. Manage the MultioutputRegressor cases.
    For darts RegressionModel only.
    TODO implement a test to not recompute each time the shap values in case of multioutput flag is True.
    """

    def __init__(
        self,
        model: GlobalForecastingModel,
        background_series: Union[TimeSeries, Sequence[TimeSeries]],
        background_past_covariates: Union[TimeSeries, Sequence[TimeSeries]],
        background_future_covariates: Union[TimeSeries, Sequence[TimeSeries]],
        background_nb_samples: Optional[int] = None,
    ):

        self.model = model
        self.multioutput = self.model.model._get_tags()["multioutput"]
        self.target_dim = self.model.input_dim["target"]

        self.background_X = self._create_RegressionModel_shap_X(
            background_series,
            background_past_covariates,
            background_future_covariates,
            background_nb_samples,
        )

        self.target_dict = {c: i for i, c in enumerate(background_series.columns)}

        if (self.target_dim > 1 or self.model.output_chunk_length > 1) and (
            not self.multioutput
        ):
            self.explainers = {}
            for i in range(self.model.output_chunk_length):
                self.explainers[i] = {}
                for j in range(self.target_dim):
                    self.explainers[i][j] = shap.Explainer(
                        self.model.model.estimators_[i + j], self.background_X
                    )
                    # Special case of trees, where we don't want to depend on a background (faster in general)
                    # Warning: Randomforest is quite slow.
                    if isinstance(self.explainers[i][j], shap.explainers._tree.Tree):
                        self.explainers[i][j] = shap.TreeExplainer(
                            self.model.model.estimators_[i + j]
                        )
        else:
            self.explainers = shap.Explainer(self.model.model, self.background_X)
            if isinstance(self.explainers, shap.explainers._tree.Tree):
                self.explainers = shap.TreeExplainer(self.model.model)

        self.cache_explainers = None
        self.cache_foreground_series = None
        self.cache_foreground_past_covariates = None
        self.cache_foreground_future_covariates = None
        self.cache_foreground_X = None
        self.foreground_changed = True

    def shap_values(
        self,
        foreground_series: Union[TimeSeries, Sequence[TimeSeries]],
        foreground_past_covariates: Optional[Union[TimeSeries, Sequence[TimeSeries]]],
        foreground_future_covariates: Optional[Union[TimeSeries, Sequence[TimeSeries]]],
        horizon: Optional[int] = None,
        target_name: Optional[str] = None,
    ):
        "-> shap._explanation.Explanation"

        if not all(
            foreground_series.time_index
            == foreground_past_covariates.time_index
            == foreground_future_covariates.time_index
        ):
            logger.warning(
                "The series and covariates don't share the same time index. We will take the time index common to all."
            )

        (
            foreground_series,
            foreground_past_covariates,
            foreground_future_covariates,
        ) = retain_period_common_to_all(
            [
                foreground_series,
                foreground_past_covariates,
                foreground_future_covariates,
            ]
        )

        # We don't recompute if the foreground is the same as the last computation
        if (
            (self.cache_foreground_series != foreground_series)
            or (self.cache_foreground_past_covariates != foreground_past_covariates)
            or (self.cache_foreground_future_covariates != foreground_future_covariates)
        ):

            foreground_X = self._create_RegressionModel_shap_X(
                foreground_series,
                foreground_past_covariates,
                foreground_future_covariates,
                None,
            )
            self.cache_foreground_series = foreground_series
            self.cache_foreground_past_covariates = foreground_past_covariates
            self.cache_foreground_future_covariates = foreground_future_covariates

            self.foreground_changed = True

            self.cache_foreground_X = foreground_X.copy()
        else:
            self.foreground_changed = False

        return self.shap_values_from_X(self.cache_foreground_X, horizon, target_name)

    def shap_values_from_X(
        self, X, horizon: Optional[int] = None, target_name: Optional[str] = None
    ):
        "-> shap._explanation.Explanation"

        # Multioutput case
        if self.target_dim > 1 or self.model.output_chunk_length > 1:

            # MultioutputRegressor case
            if isinstance(self.explainers, dict):
                assert isinstance(self.model.model, MultiOutputRegressor)
                shap_values = self.explainers[horizon][self.target_dict[target_name]](X)
            # Supported sikit-learn multioutput case
            else:
                # We compute it only once
                if self.foreground_changed:
                    self.cache_explainers = self.explainers(X)
                shap_values = self.cache_explainers[
                    :,
                    :,
                    horizon * self.target_dict[target_name]
                    + self.target_dict[target_name],
                ]
        else:
            shap_values = self.explainers(X)

        # We add one property to the shap._explanation.Explanation which is the index of time steps we explain
        shap_values.time_index = X.index

        # When MultiOutputRegressor, or when pure univariate and output_chun_legth = 1, we need to ravel base_values
        # to make work force plot.
        shap_values.base_values = shap_values.base_values.ravel()

        return shap_values

    def _create_RegressionModel_shap_X(
        self, target_series, past_covariates, future_covariates, n_samples=None
    ):
        """
        Helper function that creates training/validation matrices (X and y as required in sklearn), given series and
        max_samples_per_ts.

        Partially adapted from _create_lagged_data funtion in regression_model

        X has the following structure:
        lags_target | lags_past_covariates | lags_future_covariates

        Where each lags_X has the following structure (lags_X=[-2,-1] and X has 2 components):
        lag_-2_comp_1_X | lag_-2_comp_2_X | lag_-1_comp_1_X | lag_-1_comp_2_X

        y has the following structure (output_chunk_length=4 and target has 2 components):
        lag_+0_comp_1_target | lag_+0_comp_2_target | ... | lag_+3_comp_1_target | lag_+3_comp_2_target
        """

        # ensure list of TimeSeries format
        if isinstance(target_series, TimeSeries):
            target_series = [target_series]
            past_covariates = [past_covariates] if past_covariates else None
            future_covariates = [future_covariates] if future_covariates else None

        Xs = []
        # iterate over series
        for idx, target_ts in enumerate(target_series):
            covariates = [
                (
                    past_covariates[idx].pd_dataframe(copy=False)
                    if past_covariates
                    else None,
                    self.model.lags.get("past"),
                ),
                (
                    future_covariates[idx].pd_dataframe(copy=False)
                    if future_covariates
                    else None,
                    self.model.lags.get("future"),
                ),
            ]

            df_X = []
            df_target = target_ts.pd_dataframe(copy=False)

            # X: target lags
            if "target" in self.model.lags:
                for lag in self.model.lags["target"]:
                    self.model.lags["target"]
                    df_tmp = df_target.shift(-lag)
                    df_X.append(
                        df_tmp.rename(
                            columns={
                                c: c + "_target_lag" + str(lag) for c in df_tmp.columns
                            }
                        )
                    )

            # X: covariate lags
            for idx, (df_cov, lags) in enumerate(covariates):
                if lags:
                    for lag in lags:
                        df_tmp = df_cov.shift(-lag)
                        if idx == 0:
                            cov_type = "past"
                        else:
                            cov_type = "fut"
                        df_X.append(
                            df_tmp.rename(
                                columns={
                                    c: c + "_" + cov_type + "_cov_lag" + str(lag)
                                    for c in df_tmp.columns
                                }
                            )
                        )

            # combine lags
            Xs.append(pd.concat(df_X, axis=1).dropna())

        # combine samples from all series
        X = pd.concat(Xs, axis=0)

        if n_samples:
            X = shap.utils.sample(n_samples, X)

        return X
