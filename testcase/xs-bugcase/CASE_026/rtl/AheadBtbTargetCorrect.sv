// Extracted from preserve-aggregate AheadBtb.sv:525-605 (2026-10-18).
// The train type retains the packed fields read by this combinational cone.
typedef struct packed {
  logic [1:0] branchType;
  logic [1:0] rasAction;
} abtb_attribute_t;

typedef struct packed {
  logic hit;
  abtb_attribute_t attribute_0;
  logic [4:0] position;
  logic [21:0] targetLowerBits;
} abtb_entry_t;

typedef struct packed {
  struct packed {
    logic [4:0] cfiPosition;
    struct packed {logic [48:0] addr;} target;
    abtb_attribute_t attribute_0;
  } finalPrediction;
  struct packed {abtb_entry_t [7:0] entries;} abtbMeta;
} abtb_train_t;

module AheadBtbTargetCorrect (
  input abtb_train_t t1_train,
  input t1_fire,
  input [3:0] bankMask,
  output out_hit,
  output [7:0] out_selected,
  output out_need_correct,
  output out_write_bank0
);
  wire        t1_positionEqualMask_0 =
    t1_train.abtbMeta.entries[3'h0].position == t1_train.finalPrediction.cfiPosition;
  wire        t1_positionEqualMask_1 =
    t1_train.abtbMeta.entries[3'h1].position == t1_train.finalPrediction.cfiPosition;
  wire        t1_positionEqualMask_2 =
    t1_train.abtbMeta.entries[3'h2].position == t1_train.finalPrediction.cfiPosition;
  wire        t1_positionEqualMask_3 =
    t1_train.abtbMeta.entries[3'h3].position == t1_train.finalPrediction.cfiPosition;
  wire        t1_positionEqualMask_4 =
    t1_train.abtbMeta.entries[3'h4].position == t1_train.finalPrediction.cfiPosition;
  wire        t1_positionEqualMask_5 =
    t1_train.abtbMeta.entries[3'h5].position == t1_train.finalPrediction.cfiPosition;
  wire        t1_positionEqualMask_6 =
    t1_train.abtbMeta.entries[3'h6].position == t1_train.finalPrediction.cfiPosition;
  wire        t1_positionEqualMask_7 =
    t1_train.abtbMeta.entries[3'h7].position == t1_train.finalPrediction.cfiPosition;
  wire        t1_hitMask_0 =
    t1_train.abtbMeta.entries[3'h0].hit & t1_positionEqualMask_0
    & t1_train.abtbMeta.entries[3'h0].attribute_0.rasAction == t1_train.finalPrediction.attribute_0.rasAction
    & t1_train.abtbMeta.entries[3'h0].attribute_0.branchType == t1_train.finalPrediction.attribute_0.branchType;
  wire        t1_hitMask_1 =
    t1_train.abtbMeta.entries[3'h1].hit & t1_positionEqualMask_1
    & t1_train.abtbMeta.entries[3'h1].attribute_0.rasAction == t1_train.finalPrediction.attribute_0.rasAction
    & t1_train.abtbMeta.entries[3'h1].attribute_0.branchType == t1_train.finalPrediction.attribute_0.branchType;
  wire        t1_hitMask_2 =
    t1_train.abtbMeta.entries[3'h2].hit & t1_positionEqualMask_2
    & t1_train.abtbMeta.entries[3'h2].attribute_0.rasAction == t1_train.finalPrediction.attribute_0.rasAction
    & t1_train.abtbMeta.entries[3'h2].attribute_0.branchType == t1_train.finalPrediction.attribute_0.branchType;
  wire        t1_hitMask_3 =
    t1_train.abtbMeta.entries[3'h3].hit & t1_positionEqualMask_3
    & t1_train.abtbMeta.entries[3'h3].attribute_0.rasAction == t1_train.finalPrediction.attribute_0.rasAction
    & t1_train.abtbMeta.entries[3'h3].attribute_0.branchType == t1_train.finalPrediction.attribute_0.branchType;
  wire        t1_hitMask_4 =
    t1_train.abtbMeta.entries[3'h4].hit & t1_positionEqualMask_4
    & t1_train.abtbMeta.entries[3'h4].attribute_0.rasAction == t1_train.finalPrediction.attribute_0.rasAction
    & t1_train.abtbMeta.entries[3'h4].attribute_0.branchType == t1_train.finalPrediction.attribute_0.branchType;
  wire        t1_hitMask_5 =
    t1_train.abtbMeta.entries[3'h5].hit & t1_positionEqualMask_5
    & t1_train.abtbMeta.entries[3'h5].attribute_0.rasAction == t1_train.finalPrediction.attribute_0.rasAction
    & t1_train.abtbMeta.entries[3'h5].attribute_0.branchType == t1_train.finalPrediction.attribute_0.branchType;
  wire        t1_hitMask_6 =
    t1_train.abtbMeta.entries[3'h6].hit & t1_positionEqualMask_6
    & t1_train.abtbMeta.entries[3'h6].attribute_0.rasAction == t1_train.finalPrediction.attribute_0.rasAction
    & t1_train.abtbMeta.entries[3'h6].attribute_0.branchType == t1_train.finalPrediction.attribute_0.branchType;
  wire        t1_hitMask_7 =
    t1_train.abtbMeta.entries[3'h7].hit & t1_positionEqualMask_7
    & t1_train.abtbMeta.entries[3'h7].attribute_0.rasAction == t1_train.finalPrediction.attribute_0.rasAction
    & t1_train.abtbMeta.entries[3'h7].attribute_0.branchType == t1_train.finalPrediction.attribute_0.branchType;
  wire        t1_hit =
    t1_hitMask_0 | t1_hitMask_1 | t1_hitMask_2 | t1_hitMask_3 | t1_hitMask_4
    | t1_hitMask_5 | t1_hitMask_6 | t1_hitMask_7;
  wire [7:0]  t1_hitMaskOH_enc =
    t1_hitMask_0
      ? 8'h1
      : t1_hitMask_1
          ? 8'h2
          : t1_hitMask_2
              ? 8'h4
              : t1_hitMask_3
                  ? 8'h8
                  : t1_hitMask_4
                      ? 8'h10
                      : t1_hitMask_5
                          ? 8'h20
                          : t1_hitMask_6 ? 8'h40 : {t1_hitMask_7, 7'h0};
  wire        t1_needCorrectTarget =
    t1_hit & (&t1_train.finalPrediction.attribute_0.branchType)
    & ((t1_hitMaskOH_enc[0] ? t1_train.abtbMeta.entries[3'h0].targetLowerBits : 22'h0)
       | (t1_hitMaskOH_enc[1] ? t1_train.abtbMeta.entries[3'h1].targetLowerBits : 22'h0)
       | (t1_hitMaskOH_enc[2] ? t1_train.abtbMeta.entries[3'h2].targetLowerBits : 22'h0)
       | (t1_hitMaskOH_enc[3] ? t1_train.abtbMeta.entries[3'h3].targetLowerBits : 22'h0)
       | (t1_hitMaskOH_enc[4] ? t1_train.abtbMeta.entries[3'h4].targetLowerBits : 22'h0)
       | (t1_hitMaskOH_enc[5] ? t1_train.abtbMeta.entries[3'h5].targetLowerBits : 22'h0)
       | (t1_hitMaskOH_enc[6] ? t1_train.abtbMeta.entries[3'h6].targetLowerBits : 22'h0)
       | (t1_hitMaskOH_enc[7]
            ? t1_train.abtbMeta.entries[3'h7].targetLowerBits
            : 22'h0)) != t1_train.finalPrediction.target.addr[21:0];
  wire        _GEN_23 = t1_fire & t1_needCorrectTarget;
  wire        _GEN_24 = _GEN_23 & bankMask[0];

  assign out_hit = t1_hit;
  assign out_selected = t1_hitMaskOH_enc;
  assign out_need_correct = t1_needCorrectTarget;
  assign out_write_bank0 = _GEN_24;
endmodule
