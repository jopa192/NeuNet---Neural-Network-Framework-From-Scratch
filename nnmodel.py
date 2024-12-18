import numpy as np
from typing import Type, List, Tuple, Dict
from layers import Layer, Dense
from losses import Loss
from optimizers import Optimizer
from data_utils import DataLoader
from lr_schedulers import LRScheduler


class NeuralNetwork:
    def __init__(self, architecture: list = []) -> None:        
        """Initializes the neural network by setting up an empty list for layers and a placeholder for the loss function.
        """
        
        self.layers: List[Type[Layer]] = []
        self.trainable: List[Type[Dense]] = []
        self.loss: Type[Loss] = None
        self.optimizer: Type[Optimizer] = None
        
        for layer in architecture:
            self.add_layer(layer)
        
    def add_layer(self, layer: Type[Layer]) -> None:
        """Adds a layer to the neural network. The first layer must be a linear layer.

        Args:
            layer (Type[Layer]): The layer to be added. If it is first layer, it should be Linear.

        Raises:
            ValueError: If the first layer is not a linear layer.
        """
        
        if len(self.layers) == 0 and not hasattr(layer, "weights"):
            raise ValueError("First layer must be Linear")
        
        self.layers.append(layer)
        
        if hasattr(layer, "weights"):
            self.trainable.append(layer)
        
    def config(self, loss_func: Type[Loss], optimizer: Type[Optimizer]) -> None:
        """Configures the neural network with a loss function for training

        Args:
            loss_func (Type[Loss]): The loss function class to be used for training.
            optimizer (Type[Optimizer]): The optimizer used for updating parameters.
        """
        
        self.loss: Type[Loss] = loss_func
        self.optimizer: Type[Optimizer] = optimizer
        
    def train(self, train_data: DataLoader, n_epochs: int, val_data: DataLoader | None = None, *,
              lr_scheduler: Type[LRScheduler] | None = None, print_every: int=1, return_best: bool = False,
              patience: int = -1, min_delta: int = 0) -> None:
        """Trains the neural network using the provided dataset for a specified number of epochs with backpropagation.

        Args:
            train_data (DataLoader): Data loader containig training feature data and target values.
            n_epochs (int): Number of epochs to train the network.
            val_data (DataLoader | None, optional): Data loader containig validation feature data and target values. Defaults to None.
            lr_scheduler (Type[LRScheduler] | None, optional): Determines the learning rate based on the current epoch. Defaults to None.
            print_every (int, optional): How often the training info is printed. Defaults to 1.
            return_best (bool, optional): If True, the model applies the parameters recorded at the epoch with the smallest loss (val loss if val data is provided, otherwise train loss). Automatically set to True if patience is provided. Defaults to False.
            patience (int, optional): Number of epochs with no improvement to wait before stopping. If -1, early stop will not be included in training process. Defaults to -1.
            min_delta (int, optional): Minimum change in validation loss to qualify as an improvement. Defaults to 0.
        """
        
        # Returning best parameters is automatically activated if early stop patience is provided
        if patience >= 0:
            return_best = True
            
        self.losses_log = []
        
        best_params: List[Dict[str, np.ndarray]] | None = None
        es_counter: int = 0
        for epoch in range(1, n_epochs+1):
            # Training and validation loss
            running_loss: np.float64 = 0.
            running_val_loss: np.float64 = 0. # Calculated only if validation dataset is provided
            
            # Iterating through batches
            for sample_batch, target in train_data:
                output, params, l1_penalty, l2_penalty = self.forward(sample_batch, training=True)
                
                running_loss += self.loss.calculate_loss(output, target) + l1_penalty + l2_penalty
                
                self.backward()
                
                self.optimizer.gradient_step()
                
                # Training validation
                if val_data is not None:
                    for val_sample_batch, val_target in val_data:
                        val_output, _, l1_val_penalty, l2_val_penalty = self.forward(val_sample_batch, training=False)
                        
                        running_val_loss += self.loss.calculate_loss(val_output, val_target, training=False) + l1_val_penalty + l2_val_penalty
                
                # Adjusting learning rate if learning rate scheduler is provided
                if lr_scheduler is not None:
                    lr_scheduler.schedule(epoch)
                
            train_loss = running_loss / len(train_data)
            val_loss = running_val_loss / len(val_data) if val_data is not None else None
            # If validation loss does not exist (validation data is not provided),
            # training loss serves as criterion for model efficiency, otherwise validation loss is criterion for model efficiency
            criterion_loss = val_loss if val_loss is not None else train_loss
            
            self.losses_log.append((train_loss, val_loss) if val_loss is not None else (train_loss,))
            
            # Printing efficiency of model for current epoch
            if epoch % print_every == 0:
                self.monitor_progress(epoch, train_loss, val_loss, self.optimizer.learning_rate)
            
            # Comparing losses for best model parameters
            if return_best:
                if best_params is None: # Best params is None if it is first training iteration
                    best_params = {"params": params, "loss": criterion_loss}
                
                # Early stop
                if criterion_loss < best_params["loss"] - min_delta:
                    es_counter = 0
                    best_params = {"params": params, "loss": criterion_loss}
                else:
                    if patience >= 0:
                        es_counter += 1
                        if es_counter >= patience:
                            break
                
        if best_params is not None:
            self.apply_params(best_params["params"])
            print(f"Best {"val" if val_loss is not None else "train"} loss: {best_params["loss"]}")
        
    def forward(self, inputs: np.ndarray, training: bool = True) -> Tuple[np.ndarray, List[Dict[str, np.ndarray]]]:
        """Performs a forward pass through the neural network.

        Args:
            inputs (np.ndarray): 
            training (bool, optional): Indicates whether the network is in training mode. Defaults to True.
            
        Returns: 
            Tuple[np.ndarray, List[Dict[str, np.ndarray]]]: Final output of the forward pass (np.ndarray) and list of dictionaries with trainable parameters (weights, biases)
        """
        
        output = inputs.copy()
        params = []
        l1_penalty = 0.
        l2_penalty = 0.
        
        for layer in self.layers:
            if hasattr(layer, "dropout_rate"):
                layer.forward(output, training=training)
            else:
                layer.forward(output)
                if hasattr(layer, "weights"):
                    params.append({"weights": layer.weights, "biases": layer.biases})
                    if layer.l1_lambda > 0: l1_penalty += layer.l1_regularize()
                    if layer.l2_lambda > 0: l2_penalty += layer.l2_regularize()
            output = layer.output
        
        return output, params, l1_penalty, l2_penalty
    
    def backward(self) -> None:
        """Performs backpropagation through the network, starting with the loss function and propagating the gradients backward through each layer.
        """
        
        self.loss.backward()
        d_output = self.loss.d_output
        for layer in reversed(self.layers):
            layer.backward(d_output)
            d_output = layer.d_output
            
    def apply_params(self, params: List[Dict["str", np.ndarray]]) -> None:
        for dense, params in zip(self.trainable, params):
            dense.weights = params["weights"]
            dense.biases = params["biases"]            
            
    def predict(self, inputs: np.ndarray) -> np.ndarray | float:
        predictions, _, _, _ = self.forward(inputs, training=False) 
        return predictions
    
    def plot_loss_history(self):
        import matplotlib.pyplot as plt
        
        losses_log = np.array(self.losses_log)
        epochs = np.arange(losses_log.shape[0]) + 1
        
        plt.figure(figsize=(8, 6))
        plt.plot(epochs, losses_log[:, 0], label='Training Loss', color='b')
        if losses_log.shape[1] == 2:
            plt.plot(epochs, losses_log[:, 1], label='Validation Loss', color='r')
        plt.xlabel('Epochs')
        plt.ylabel('Loss')
        plt.title('Loss vs Epochs')
        plt.legend()
        plt.grid()
        plt.show()
    
    @staticmethod
    def monitor_progress(epoch: int, loss: float, val_loss: float | None, lr: float) -> None:
        print_str = f"Epoch {epoch} : loss {loss} "
        
        if val_loss is not None:
            print_str += f"val loss {val_loss} "
            
        print_str += f"lr {lr:.7f}"
            
        print(print_str)