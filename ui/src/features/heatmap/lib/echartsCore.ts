// Tree-shaken echarts build: only the treemap chart type + the tooltip,
// continuous visualMap, and canvas renderer this dashboard actually uses.
// Importing the full `echarts` package (as `echarts-for-react`'s default
// export does) pulls in every chart type and pushed the heatmap's lazy
// chunk past 1MB; this trims it to just what a treemap needs.
import * as echarts from 'echarts/core';
import { TreemapChart } from 'echarts/charts';
import { TooltipComponent, VisualMapComponent, VisualMapContinuousComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([TreemapChart, TooltipComponent, VisualMapComponent, VisualMapContinuousComponent, CanvasRenderer]);

export default echarts;
