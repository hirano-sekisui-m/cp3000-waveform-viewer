declare module "react-plotly.js" {
  import * as React from "react";
  import * as Plotly from "plotly.js-dist-min";

  export interface PlotParams {
    data: any[];
    layout: any;
    config?: any;
    frames?: any[];
    revision?: number;
    onInitialized?: (figure: any, graphDiv: HTMLElement) => void;
    onUpdate?: (figure: any, graphDiv: HTMLElement) => void;
    onPurge?: (figure: any, graphDiv: HTMLElement) => void;
    onError?: (err: Error) => void;
    useResizeHandler?: boolean;
    debug?: boolean;
    style?: React.CSSProperties;
    className?: string;
    divId?: string;
  }

  export default class Plot extends React.Component<PlotParams> {}
}
