import time

from metal.tuners.tuner import ModelTuner


class RandomSearchTuner(ModelTuner):
    """A tuner for models

    Args:
        model: (nn.Module) The model class to train (uninitiated)
        log_dir: The directory in which to save intermediate results
            If no log_dir is given, the model tuner will attempt to keep
            best trained model in memory.
    """

    def search(
        self,
        search_space,
        X_dev,
        Y_dev,
        init_args=[],
        train_args=[],
        init_kwargs={},
        train_kwargs={},
        max_search=None,
        shuffle=True,
        verbose=True,
        **score_kwargs,
    ):
        """
        Args:
            search_space: see config_generator() documentation
            X_dev: The appropriate input for evaluating the given model
            Y_dev: An [n] or [n, 1] tensor of gold labels in {0,...,K_t} or a
                t-length list of such tensors if model.multitask=True.
            init_args: (list) positional args for initializing the model
            train_args: (list) positional args for training the model
            init_kwargs: (dict) keyword args for initializing the model
            train_kwargs: (dict) keyword args for training the model
            max_search: see config_generator() documentation
            shuffle: see config_generator() documentation

        Returns:
            best_model: the highest performing trained model

        Note: Initialization is performed by ModelTuner instead of passing a
        pre-initialized model so that tuning may be performed over all model
        parameters, including the network architecture (which is defined before
        the train loop).
        """
        # Clear run stats
        self.run_stats = []
        configs = self.config_generator(search_space, max_search, shuffle)
        best_index = 0
        best_score = -1
        start_time = time.time()
        for i, config in enumerate(configs):
            # Unless seeds are given explicitly, give each config a unique one
            if config.get("seed", None) is None:
                config["seed"] = self.seed + i

            score, model = self._train_model(
                i,
                config,
                X_dev,
                Y_dev,
                init_args=init_args,
                train_args=train_args,
                init_kwargs=init_kwargs,
                train_kwargs=train_kwargs,
                verbose=verbose,
                **score_kwargs,
            )

            if score > best_score:
                best_index = i + 1
                best_score = score
                best_config = config
                self._save_best_model(model)

                # Keep track of running statistics
                time_elapsed = time.time() - start_time
                self.run_stats.append(
                    {
                        "time_elapsed": time_elapsed,
                        "best_score": best_score,
                        "best_config": best_config,
                    }
                )

        print("=" * 60)
        print(f"[SUMMARY]")
        print(f"Best model: [{best_index}]")
        print(f"Best config: {best_config}")
        print(f"Best score: {best_score}")
        print("=" * 60)

        return self._load_best_model(clean_up=True)
