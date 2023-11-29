import pandas as pd
import matplotlib.pyplot as plt
import os
import re
import glob
from datasets import load_dataset
import datasets
from datasets import load_dataset, Dataset


"""## 2. Load and prepare imdb dataset

we will use the [imdb](https://huggingface.co/datasets/imdb) Large Movie Review Dataset. This is a dataset for binary sentiment classification containing substantially more data than previous benchmark datasets. We provide a set of 25,000 highly polar movie reviews for training, and 25,000 for testing. There is additional unlabeled data for use as well.

"""

dataset_id = "imdb"

"""To load the `samsum` dataset, we use the `load_dataset()` method from the 🤗 Datasets library.

"""

from datasets import load_dataset

# Load dataset from the hub
imdb = load_dataset(dataset_id)

# print(f"Train dataset size: {len(dataset['train'])}")
# print(f"Test dataset size: {len(dataset['test'])}")



imdb['train']['label']

train_df = pd.read_csv('/home/yumin/hare-hate-speech/data/implicit-hate/IH_train.csv')
validataion_df = pd.read_csv('/home/yumin/hare-hate-speech/data/implicit-hate/IH_val.csv')
test_df = pd.read_csv('/home/yumin/hare-hate-speech/data/implicit-hate/IH_test.csv')

import pandas as pd

def map_label_for_classification(label):
    if label == "implicit_hate":
        return 1
    elif label == "explicit_hate":
        return 2
    elif label == "not_hate":
        return 0
    else:
        return None  # or handle the case when the label is different

train_df['label_num'] = train_df['class'].apply(map_label_for_classification)
validataion_df['label_num'] = validataion_df['class'].apply(map_label_for_classification)
test_df['label_num'] = test_df['class'].apply(map_label_for_classification)
train_df = train_df.reset_index()
test_df = test_df.reset_index()
validataion_df = validataion_df.reset_index()

full_train_dataset = Dataset.from_pandas(train_df[['post','label_num']])
full_validataion_dataset = Dataset.from_pandas(validataion_df[['post','label_num']])
full_test_dataset = Dataset.from_pandas(test_df[['post','label_num']])

dataset = datasets.DatasetDict({"train":full_train_dataset,
                                "validation" : full_validataion_dataset,
                                "test" : full_test_dataset})
dataset

imdb

"""Lets checkout an example of the dataset."""

dataset['train'][1]

"""To train our model we need to convert our inputs (text) to token IDs. This is done by a 🤗 Transformers Tokenizer. If you are not sure what this means check out [chapter 6](https://huggingface.co/course/chapter6/1?fw=tf) of the Hugging Face Course."""

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

model_id="google/flan-t5-small"

# Load tokenizer of FLAN-t5-base
tokenizer = AutoTokenizer.from_pretrained(model_id)

"""before we can start training we need to preprocess our data. Abstractive flan t5 is good for a text2text-generation task. This means our model will take a text as input and generate a text as output. For this we want to understand how long our input and output will be to be able to efficiently batch our data.
- as result, we should to convert label from int to string
"""

dataset

import pandas as pd
from datasets import Dataset
import random

# dataset['train'] = dataset['train'].shuffle(seed=42).select(range(2000))
# dataset['test'] = dataset['test'].shuffle(seed=42).select(range(1000))

# dataset['train'] = dataset['train'].shuffle(seed=42)

train_df = pd.DataFrame(dataset['train'])
test_df = pd.DataFrame(dataset['test'])
dataset.clear()

train_df['label'] = train_df['label_num'].astype(str)
test_df['label'] = test_df['label_num'].astype(str)
dataset['train'] = Dataset.from_pandas(train_df)
dataset['test'] = Dataset.from_pandas(test_df)

dataset['train']['label']

from datasets import concatenate_datasets

# The maximum total input sequence length after tokenization.
# Sequences longer than this will be truncated, sequences shorter will be padded.
tokenized_inputs = concatenate_datasets([dataset["train"], dataset["test"]]).map(lambda x: tokenizer(x["post"], truncation=True), batched=True, remove_columns=['post', 'label'])
max_source_length = max([len(x) for x in tokenized_inputs["input_ids"]])
print(f"Max source length: {max_source_length}")

# The maximum total sequence length for target text after tokenization.
# Sequences longer than this will be truncated, sequences shorter will be padded."
tokenized_targets = concatenate_datasets([dataset["train"], dataset["test"]]).map(lambda x: tokenizer(x["label"], truncation=True), batched=True, remove_columns=['post', 'label'])
max_target_length = max([len(x) for x in tokenized_targets["input_ids"]])
print(f"Max target length: {max_target_length}")

def preprocess_function(sample, padding="max_length"):
    # add prefix to the input for t5
    inputs = [item for item in sample["post"]]

    # tokenize inputs
    model_inputs = tokenizer(inputs, max_length=max_source_length, padding=padding, truncation=True)

    # Tokenize targets with the `text_target` keyword argument
    labels = tokenizer(text_target=sample["label"], max_length=max_target_length, padding=padding, truncation=True)

    # If we are padding here, replace all tokenizer.pad_token_id in the labels by -100 when we want to ignore
    # padding in the loss.
    if padding == "max_length":
        labels["input_ids"] = [
            [(l if l != tokenizer.pad_token_id else -100) for l in label] for label in labels["input_ids"]
        ]

    model_inputs["labels"] = labels["input_ids"]
    return model_inputs

tokenized_dataset = dataset.map(preprocess_function, batched=True, remove_columns=['post', 'label'])
print(f"Keys of tokenized dataset: {list(tokenized_dataset['train'].features)}")

"""## 3. Fine-tune and evaluate FLAN-T5

After we have processed our dataset, we can start training our model. Therefore we first need to load our [FLAN-T5](https://huggingface.co/models?search=flan-t5) from the Hugging Face Hub. In the example we are using a instance with a NVIDIA V100 meaning that we will fine-tune the `base` version of the model.
_I plan to do a follow-up post on how to fine-tune the `xxl` version of the model using Deepspeed._

"""

from transformers import AutoModelForSeq2SeqLM

# huggingface hub model id
model_id="google/flan-t5-small"

# load model from the hub
model = AutoModelForSeq2SeqLM.from_pretrained(model_id)

"""We want to evaluate our model during training. The `Trainer` supports evaluation during training by providing a `compute_metrics`.  
The most commonly used metrics to evaluate summarization task is [rogue_score](https://en.wikipedia.org/wiki/ROUGE_(metric)) short for Recall-Oriented Understudy for Gisting Evaluation). This metric does not behave like the standard accuracy: it will compare a generated summary against a set of reference summaries

We are going to use `evaluate` library to evaluate the `rogue` score.
"""

import evaluate
import nltk
import numpy as np
from nltk.tokenize import sent_tokenize
nltk.download("punkt")

# Metric
metric = evaluate.load("f1")

# helper function to postprocess text
def postprocess_text(preds, labels):
    preds = [pred.strip() for pred in preds]
    labels = [label.strip() for label in labels]

    # rougeLSum expects newline after each sentence
    preds = ["\n".join(sent_tokenize(pred)) for pred in preds]
    labels = ["\n".join(sent_tokenize(label)) for label in labels]

    return preds, labels

def compute_metrics(eval_preds):
    preds, labels = eval_preds
    if isinstance(preds, tuple):
        preds = preds[0]
    decoded_preds = tokenizer.batch_decode(preds, skip_special_tokens=True)
    # Replace -100 in the labels as we can't decode them.
    labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
    decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)

    # Some simple post-processing
    decoded_preds, decoded_labels = postprocess_text(decoded_preds, decoded_labels)

    result = metric.compute(predictions=decoded_preds, references=decoded_labels, average='macro')
    result = {k: round(v * 100, 4) for k, v in result.items()}
    prediction_lens = [np.count_nonzero(pred != tokenizer.pad_token_id) for pred in preds]
    result["gen_len"] = np.mean(prediction_lens)
    return result

"""Before we can start training is to create a `DataCollator` that will take care of padding our inputs and labels. We will use the `DataCollatorForSeq2Seq` from the 🤗 Transformers library."""

from transformers import DataCollatorForSeq2Seq

# we want to ignore tokenizer pad token in the loss
label_pad_token_id = -100
# Data collator
data_collator = DataCollatorForSeq2Seq(
    tokenizer,
    model=model,
    label_pad_token_id=label_pad_token_id,
    pad_to_multiple_of=8
)

"""The last step is to define the hyperparameters (`TrainingArguments`) we want to use for our training. We are leveraging the [Hugging Face Hub](https://huggingface.co/models) integration of the `Trainer` to automatically push our checkpoints, logs and metrics during training into a repository."""

from huggingface_hub import HfFolder
from transformers import Seq2SeqTrainer, Seq2SeqTrainingArguments

# # Hugging Face repository id
repository_id = f"{model_id.split('/')[1]}-imdb-text-classification"

# Define training args
training_args = Seq2SeqTrainingArguments(
    output_dir=repository_id,
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    predict_with_generate=True,
    fp16=False, # Overflows with fp16
    learning_rate=3e-4,

    num_train_epochs=2,
    # logging & evaluation strategies
    logging_dir=f"{repository_id}/logs",
    logging_strategy="epoch",
    # logging_steps=1000,
    evaluation_strategy="no",
    save_strategy="epoch",
    save_total_limit=2,
    load_best_model_at_end=False,
    # metric_for_best_model="overall_f1",
    # push to hub parameters
    report_to="tensorboard",
    # push_to_hub=True,
    # hub_strategy="every_save",
    # hub_model_id=repository_id,
    # hub_token=HfFolder.get_token(),
)

# Create Trainer instance
trainer = Seq2SeqTrainer(
    model=model,
    args=training_args,
    data_collator=data_collator,
    train_dataset=tokenized_dataset["train"],
    eval_dataset=tokenized_dataset["test"],
    compute_metrics=compute_metrics,
)

"""We can start our training by using the `train` method of the `Trainer`."""

# Start training
trainer.train()

"""Nice, we have trained our model. 🎉 Lets run evaluate the best model again on the test set.

"""

trainer.evaluate()

# # Save our tokenizer and create model card
# tokenizer.save_pretrained(repository_id)
# trainer.create_model_card()
# # Push the results to the hub
# trainer.push_to_hub()

"""## 4. Run Inference and Classification Report"""

from tqdm.auto import tqdm

samples_number = len(dataset['test'])
progress_bar = tqdm(range(samples_number))
predictions_list = []
labels_list = []
for i in range(samples_number):
  text = dataset['test']['post'][i]
  inputs = tokenizer.encode_plus(text, padding='max_length', max_length=512, return_tensors='pt').to('cuda')
  outputs = model.generate(inputs['input_ids'], attention_mask=inputs['attention_mask'], max_length=150, num_beams=4, early_stopping=True)
  prediction = tokenizer.decode(outputs[0], skip_special_tokens=True)
  predictions_list.append(prediction)
  labels_list.append(dataset['test']['label'][i])

  progress_bar.update(1)

str_labels_list = []
for i in range(len(labels_list)): str_labels_list.append(str(labels_list[i]))

from sklearn.metrics import classification_report, accuracy_score, f1_score

print(f"model: {model_id}")
print("Accuracy_Score: ",accuracy_score(str_labels_list, predictions_list))
print('weighted f1-score: ', f1_score(str_labels_list, predictions_list, average='weighted'))
print('macro f1-score: ', f1_score(str_labels_list, predictions_list, average='macro'))
print('micro f1-score: ', f1_score(str_labels_list, predictions_list, average='micro'))


report = classification_report(str_labels_list, predictions_list, zero_division=0, digits=4)
print(report)