# clean up
rm(list = ls())
gc()
cat("\014")

# Set wd to script directory (RStudio)
script_dir <- dirname(rstudioapi::getSourceEditorContext()$path)
setwd(script_dir)
setwd('..')
library(readr)
library(dplyr)
library(ggplot2)

# load csv
csv_file <- "test_run_seed_05520_days_001_strategy_FCFS_EVsMAX_002_CHGF_01_CHGS_00_maxGrid_2000.csv"
df <- read_csv(csv_file, show_col_types = FALSE)

df_for_ev0 <- df %>%
  filter(grepl("^ev_0", agent), field == "SoC") %>%
  mutate(time = as.POSIXct(time, origin = "1970-01-01", tz = "UTC"),
         value = as.numeric(value))

ggplot(df_for_ev0, aes(x = time, y = value)) +
  geom_line() +
  labs(x = "Time",
       y = "SoC (%)",)

