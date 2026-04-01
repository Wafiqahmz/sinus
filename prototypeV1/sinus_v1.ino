#include "Wire.h"
#include <ScioSense_ENS16x.h>
#include <SensirionI2CSgp41.h>

int V_DPUM = 12;

bool waiting_for_py = true;
String python_communication;
String arduino_communication;
String s;
char c;
int iter = 0;

void wait_for_py(String);

// ENS160 declarations
String ens160_measure(void);
ENS160 ens160;
String ENS160_output;

//SGP41 declarations
SensirionI2CSgp41 sgp41;
String sgp41_measure(void);
String sgp41_output;
uint16_t conditioning_s = 10;

// Analog Sensor
String tgs2602_measure(void);
String TGS2602_output;

String output;

//ENS160 measure
String ens160_measure() {
  if (ens160.update() == RESULT_OK) {
    if (ens160.hasNewGeneralPurposeData()) {
      ENS160_output = "";
      ENS160_output = ENS160_output + ens160.getRs0() + ",";
      ENS160_output = ENS160_output + ens160.getRs1() + ",";
      ENS160_output = ENS160_output + ens160.getRs2() + ",";
      ENS160_output = ENS160_output + ens160.getRs3();
    } else {
      ENS160_output = "No new data,,,";
    }
  } else {
    ENS160_output = "ENS160 update failed,,,";
  }
  return ENS160_output;
}

// SGP41 measure
String sgp41_measure() {
  uint16_t error;
  char errorMessage[256];
  uint16_t defaultRh = 0x8000;
  uint16_t defaultT = 0x6666;
  uint16_t srawVoc = 0;
  uint16_t srawNox = 0;

  if (conditioning_s > 0) {
    error = sgp41.executeConditioning(defaultRh, defaultT, srawVoc);
    conditioning_s--;
  } else {
    error = sgp41.measureRawSignals(defaultRh, defaultT, srawVoc, srawNox);
  }

  if (error) {
    errorToString(error, errorMessage, 256);
    sgp41_output = String("SGP41 error: ") + errorMessage;
  } else {
    sgp41_output = String(srawVoc) + "," + String(srawNox);
  }
  return sgp41_output;
}

//TGS2602 measure
String tgs2602_measure() {
  int sensorValue = analogRead(A5);                            // A5 Read analog value
  float voltage = (sensorValue / 1023.0) * 5;                  // Convert to voltage
  float sensorResistance = ((5 - voltage) / voltage) * 10000;  // Calculate sensor resistance
  TGS2602_output = String(sensorResistance);
  return TGS2602_output;
}

// ------------------------------------------------------------
void setup() {

  Wire.begin();

  Wire.setWireTimeout(3000, true);

  Serial.begin(115200);
  delay(1000);

  pinMode(V_DPUM, OUTPUT);
  digitalWrite(V_DPUM, HIGH);
  Serial.println("D12 set HIGH (power to mux)");

  // ENS160 setup
  Wire.begin();               // Make sure Wire is initialized
  ens160.begin(&Wire, 0x52);  // Use 0x53 or 0x52 depending on your address pin configuration
  Serial.println("ENS160 initializing...");
  while (ens160.init() != true) {
    Serial.print(".");
    delay(1000);
  }
  Serial.println("ENS160 init success");
  ens160.startStandardMeasure();

  // SGP41 setup
  sgp41.begin(Wire);

  uint16_t testResult, error;
  char errorMessage[256];

  error = sgp41.executeSelfTest(testResult);
  if (error) {
    errorToString(error, errorMessage, 256);
    Serial.println(errorMessage);
  } else if (testResult != 0xD400) {
    Serial.print("Self-test failed: ");
    Serial.println(testResult);
  }
}
// ------------------------------------------------------------
void loop() {

  python_communication = "";
  arduino_communication = "";

  Serial.print("_");
  while (!Serial.available()) {
    delay(10);
  }

  s = "";

  while (Serial.available()) {
    c = Serial.read();
    s = s + c;
  }

  Serial.println(s);

  //Measurements
  ENS160_output = ens160_measure();
  delay(3);

  sgp41_output = sgp41_measure();
  delay(3);

  TGS2602_output = tgs2602_measure();
  delay(3);

  python_communication = ENS160_output + "," + sgp41_output + "," + TGS2602_output + "!";
  Serial.println(python_communication);
  delay(3);
}