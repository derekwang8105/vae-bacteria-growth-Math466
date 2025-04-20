import argparse
from pathlib import Path
import logging
from matplotlib import pyplot as plt
import numpy as np
import os
import sys
import random
from datetime import datetime

from sklearn.metrics import r2_score

from growth_model import SimulationRunner
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
from train_vae.data_loading import load_simulated_data

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Parameter Validation Pipeline')
    
    parser.add_argument('--data-dir', type=Path, default='simulated_data',
                      help='Directory containing simulation data')
    parser.add_argument('--true-params', type=Path, default='simulated_data\curves1k.npz',
                      help='Path to true parameters (curves1k.npzy)')
    parser.add_argument('--simulated-params', type=Path, default='simulated_data\parameters.npy',
                      help='Path to simulated parameters (parameters.npy)')
    parser.add_argument('--predicted-params', type=Path, required=True,
                      help='Path to predicted parameters (NN-estimated-parameters.npy)')
    parser.add_argument('--output-dir', type=Path, required=True,
                      help='Directory for saving results')
    
    return parser.parse_args()

def setup_logger(output_dir: Path) -> logging.Logger:
    """Setup logging configuration"""
    log_file = output_dir / 'parameter_validation.log'
    
    logger = logging.getLogger('parameter_validation')
    logger.setLevel(logging.INFO)
    
    fh = logging.FileHandler(log_file)
    ch = logging.StreamHandler()
    
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger

def extract_model_name(predicted_params_path: Path) -> str:
    """Extract model name from the predicted parameters path
    Path structure example: train_vae_mlp_output/DeepCNNVAE_LD10_LC16_LR0.001_TS20241126_233801/NN-estimated-parameters.npy
    """
    try:
        # Get the directory containing timestamp (parent of NN-estimated-parameters.npy)
        timestamp_dir = predicted_params_path.parent
        # Get the model output directory (parent of timestamp directory)
        model_output_dir = timestamp_dir.parent
        # Get just the directory name containing the timestamp
        model_info = timestamp_dir.name
        # Extract the model name (part before _LD)
        model_name = model_info.split('_LD')[0]
        return model_name
    except Exception as e:
        logger.warning(f"Could not extract model name from path: {e}")
        return "unknown_model"

def calculate_metrics(true_values, predicted_values):
    """
    Calculate MAR and RMSE between true and predicted values.

    Parameters:
    - true_values: numpy array of ground truth values.
    - predicted_values: numpy array of predicted values.

    Returns:
    - mar: Mean Absolute Residual
    - rmse: Root Mean Square Error
    """
    # Ensure inputs are numpy arrays
    true_values = np.array(true_values)
    predicted_values = np.array(predicted_values)

    # Calculate residuals
    residuals = true_values - predicted_values

    # Calculate MAR
    mar = np.mean(np.abs(residuals))

    # Calculate RMSE
    rmse = np.sqrt(np.mean(residuals**2))

    return mar, rmse

def main():
   # Parse arguments and setup
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logger(args.output_dir)
    
    # Extract model name and create model-specific output directory
    model_name = extract_model_name(args.predicted_params)
    args.output_dir = args.output_dir / model_name
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    logger = setup_logger(args.output_dir)
    logger.info(f"Model type identified: {model_name}")
    
    try:
        logger.info("Starting parameter validation")
        
        # Load and process data
        logger.info("Loading simulation data...")
        all_data = load_simulated_data(args.data_dir, logger)
        np.random.shuffle(all_data)
        logger.info(f"Combined data shape after shuffling: {all_data.shape}")
        
        # Initialize simulation parameters
        conditions = [(1e5, 1e5, 15e4, 0), (1e10, 1e5, 15e4, 2.5e5), (1e5, 1e10, 15e4, 2.5e5), (1e5, 1e5, 15e4, 5e5)]
        
        # Load true and predicted parameters
        logger.info("Loading parameters...")
        initial_data = np.load(args.true_params)
        true_curves = initial_data['curves']
        t_eval = initial_data['t_eval']
        predicted_parameters = np.load(args.predicted_params)
        
        # Initialize SimulationRunner
        logger.info("Setting up simulation runner...")
        simulation_runner = SimulationRunner(
            num_simulations=len(predicted_parameters),
            conditions=conditions,
            t_eval=t_eval,
            param_specs=None
        )

        # Rerun simulations with estimated parameters
        logger.info("Running simulations with estimated parameters...")
        simulated_curves = np.zeros_like(true_curves)
        for i, params in enumerate(predicted_parameters):
            for j, (S0, R0, V0, A0) in enumerate(conditions):
                simulated_curves[i, j] = simulation_runner.simulate(params, S0, R0, V0, A0)
        
        # Compute R^2 scores for curves
        logger.info("Computing R² scores for curves...")
        r2_scores = np.zeros((len(conditions), 3))
        variable_names = ['S', 'R', 'N']
        
        for condition_idx in range(len(conditions)):
            for variable_idx in range(3):
                original = true_curves[:, condition_idx, variable_idx, :].flatten()
                predicted = simulated_curves[:, condition_idx, variable_idx, :].flatten()
                r2_scores[condition_idx, variable_idx] = r2_score(original, predicted)
                mar, rmse = calculate_metrics(original, predicted)
                   
                logger.info(f"Condition: S0={conditions[condition_idx][0]}, "
                          f"R0={conditions[condition_idx][1]}, "
                          f"A0={conditions[condition_idx][3]}, "
                          f"R² for {variable_names[variable_idx]}: "
                          f"{r2_scores[condition_idx, variable_idx]:.3f},MAR: {mar:.3f}, RMSE: {rmse:.3f} " )
        
        # Create plots directory
        plots_dir = args.output_dir / 'plots'
        plots_dir.mkdir(exist_ok=True)
        
        # Plot curve comparisons
        logger.info("Generating curve comparison plots...")
        for condition_idx, (S0, R0, V0, A0) in enumerate(conditions):
            for variable_idx, variable_name in enumerate(variable_names):
                original = true_curves[:, condition_idx, variable_idx, :].flatten()
                predicted = simulated_curves[:, condition_idx, variable_idx, :].flatten()

                plt.figure(figsize=(6, 6))                
                plt.scatter(original[:10000], predicted[:10000], alpha=0.2, s=5, color='blue')
                plt.plot([original[:10000].min(), original[:10000].max()],
                        [original[:10000].min(), original[:10000].max()], 'r--')
                           
                plt.title(f'{variable_name} (Condition: S0={"{:.1e}".format(S0)}, R0={"{:.1e}".format(R0)}, A0={"{:.1e}".format(A0)})')
                plt.xlabel('Original')
                plt.ylabel('Simulated with Estimated Parameters')
                plt.text(0.05, 0.95, 
                        f'R² = {r2_scores[condition_idx, variable_idx]:.3f}',
                        transform=plt.gca().transAxes,
                        verticalalignment='top')
                plt.grid(True)
                plt.savefig(plots_dir / f'curve_comparison_{variable_name}_{"{:.1e}".format(S0)}_{"{:.1e}".format(R0)}_{"{:.1e}".format(A0)}.png')
                plt.close()
        
        # Compute and plot parameter comparison
        logger.info("Computing parameter R² scores...")
        parameter_names = ['r', 'beta', 'lambda_', 'nu', 'rho', 'alpha', 'theta', 'E_max', 'MIC_S', 'MIC_R', 'mu', 'gamma']

        
        true_parameters = np.load(args.simulated_params)
        assert true_parameters.shape == predicted_parameters.shape, "Shapes of true and predicted parameters do not match."
        parameter_r2_scores = {}
        for i, param_name in enumerate(parameter_names):
            r2 = r2_score(true_parameters[:, i], predicted_parameters[:, i])
            parameter_r2_scores[param_name] = r2
            logger.info(f"{param_name}: R² = {r2:.3f}")
        
            plt.figure(figsize=(6, 6))
            plt.scatter(true_parameters[:, i], predicted_parameters[:, i], alpha=0.2, s=5, color='blue')
            plt.plot([true_parameters[:, i].min(), true_parameters[:, i].max()],
                    [true_parameters[:, i].min(), true_parameters[:, i].max()], 'r--')
            plt.title(f"Parameter: {param_name}")
            plt.xlabel("True Value")
            plt.ylabel("Predicted Value")
            plt.text(0.05, 0.95, f'R² = {r2:.3f}',
                    transform=plt.gca().transAxes,
                    verticalalignment='top')
            plt.grid(True)
            plt.savefig(plots_dir / f'parameter_comparison_{param_name}.png')
            plt.close()
            
        # Save results
        logger.info("Saving results...")
        np.savez(
            args.output_dir / 'validation_results.npz',
            curve_r2_scores=r2_scores,
            parameter_r2_scores=parameter_r2_scores,
            conditions=conditions,
            parameter_names=parameter_names,
            variable_names=variable_names
        )
        
        logger.info("Parameter validation completed successfully")
        
    except Exception as e:
        logger.error(f"Error in parameter validation: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    main()